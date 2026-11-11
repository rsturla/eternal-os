// repopush proves that an RPM repository can be updated from metadata and a delta.
// It deliberately supports only unsigned primary/filelists/other repositories.
package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/xml"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"os/signal"
	"path"
	"path/filepath"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/smithy-go"
)

const immutable = "public, max-age=31536000, immutable"

type objects []string

func (o *objects) String() string     { return strings.Join(*o, ",") }
func (o *objects) Set(s string) error { *o = append(*o, s); return nil }

type index struct {
	XMLName xml.Name `xml:"http://linux.duke.edu/metadata/repo repomd"`
	Data    []record `xml:"data"`
}
type record struct {
	Type     string `xml:"type,attr"`
	Location struct {
		Href string `xml:"href,attr"`
	} `xml:"location"`
	Checksum struct {
		Type  string `xml:"type,attr"`
		Value string `xml:",chardata"`
	} `xml:"checksum"`
}
type publisher struct {
	client         *s3.Client
	bucket, prefix string
}

func main() {
	log.SetFlags(0)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	if err := run(ctx); err != nil {
		log.Fatal(err)
	}
}

func run(ctx context.Context) error {
	endpoint := flag.String("endpoint", "", "S3 endpoint, empty for AWS")
	bucket := flag.String("bucket", "", "destination bucket")
	prefix := flag.String("prefix", "archive/x86_64", "repository prefix within bucket")
	region := flag.String("region", "us-east-1", "S3 region")
	var incoming objects
	flag.Var(&incoming, "object", "already-uploaded RPM key, repeatable; downloads only this RPM")
	flag.Parse()
	if *bucket == "" || len(incoming)+flag.NArg() == 0 {
		return errors.New("usage: repopush --bucket BUCKET [--object incoming/new.rpm] [local.rpm ...]")
	}
	if *prefix == "" || strings.HasPrefix(*prefix, "/") || path.Clean(*prefix) != *prefix || strings.HasPrefix(*prefix, "../") {
		return errors.New("prefix must be a clean, relative object prefix")
	}
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion(*region))
	if err != nil {
		return err
	}
	// Avoid optional trailing checksum extensions on S3-compatible endpoints.
	cfg.RequestChecksumCalculation = aws.RequestChecksumCalculationWhenRequired
	cfg.ResponseChecksumValidation = aws.ResponseChecksumValidationWhenRequired
	p := publisher{s3.NewFromConfig(cfg, func(o *s3.Options) {
		o.UsePathStyle = true
		if *endpoint != "" {
			o.BaseEndpoint = endpoint
		}
	}), *bucket, *prefix}
	work, err := os.MkdirTemp("", "repopush-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(work)
	// Never leave an old detached signature beside a newly unsigned index.
	_, err = p.client.HeadObject(ctx, &s3.HeadObjectInput{Bucket: &p.bucket, Key: aws.String(path.Join(p.prefix, "repodata/repomd.xml.asc"))})
	if err == nil {
		return errors.New("signed repository unsupported by this prototype")
	}
	if !notFound(err) {
		return err
	}

	delta := filepath.Join(work, "delta")
	if err := os.MkdirAll(delta, 0700); err != nil {
		return err
	}
	inputs := append([]string(nil), flag.Args()...)
	for i, key := range incoming {
		if !strings.HasSuffix(key, ".rpm") {
			return fmt.Errorf("incoming key is not an RPM: %s", key)
		}
		data, _, err := p.get(ctx, key)
		if err != nil {
			return err
		}
		file := filepath.Join(work, fmt.Sprintf("incoming-%d.rpm", i))
		if err := os.WriteFile(file, data, 0600); err != nil {
			return err
		}
		inputs = append(inputs, file)
	}
	for _, file := range inputs {
		data, err := os.ReadFile(file)
		if err != nil {
			return err
		}
		if !strings.HasSuffix(file, ".rpm") {
			return fmt.Errorf("not an RPM: %s", file)
		}
		// A checksum path prevents a reused filename from changing an old snapshot.
		sum := sha256.Sum256(data)
		rel := path.Join("Packages", hex.EncodeToString(sum[:])+".rpm")
		local := filepath.Join(delta, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(local), 0700); err != nil {
			return err
		}
		if err := os.WriteFile(local, data, 0600); err != nil {
			return err
		}
	}
	if err := command(ctx, "createrepo_c", "--no-database", "--general-compress-type=gz", delta); err != nil {
		return err
	}
	// Upload only after the RPM parser has accepted every input.
	files, err := filepath.Glob(filepath.Join(delta, "Packages", "*.rpm"))
	if err != nil {
		return err
	}
	for _, file := range files {
		if err := p.putFile(ctx, path.Join(p.prefix, "Packages", filepath.Base(file)), file, "", ""); err != nil {
			return err
		}
	}
	// An ETag conflict requires re-reading and re-merging, never a blind PUT retry.
	for attempt := range 5 {
		old := filepath.Join(work, fmt.Sprintf("old-%d", attempt))
		etag, exists, err := p.snapshot(ctx, old)
		if err != nil {
			return err
		}
		output := delta
		if exists {
			output = filepath.Join(work, fmt.Sprintf("merged-%d", attempt))
			if err := command(ctx, "mergerepo_c", "--nogroups", "--noupdateinfo", "--repo", "file://"+delta, "--repo", "file://"+old, "--all", "--omit-baseurl", "--no-database", "--compress-type=gz", "--outputdir", output); err != nil {
				return err
			}
		}
		metadata, err := filepath.Glob(filepath.Join(output, "repodata", "*"))
		if err != nil {
			return err
		}
		for _, file := range metadata {
			if filepath.Base(file) == "repomd.xml" {
				continue
			}
			if err := p.putFile(ctx, path.Join(p.prefix, "repodata", filepath.Base(file)), file, "", ""); err != nil {
				return err
			}
		}
		condition := "*"
		if exists {
			condition = ""
		}
		err = p.putFile(ctx, path.Join(p.prefix, "repodata/repomd.xml"), filepath.Join(output, "repodata/repomd.xml"), etag, condition)
		if err == nil {
			log.Printf("published s3://%s/%s", p.bucket, p.prefix)
			return nil
		}
		if !apiCode(err, "PreconditionFailed", "ConditionalRequestConflict") {
			return err
		}
		log.Printf("index changed; re-read and merge again, attempt %d", attempt+2)
	}
	return errors.New("repository kept changing after five publish attempts; rerun")
}

func (p publisher) snapshot(ctx context.Context, dir string) (string, bool, error) {
	data, etag, err := p.get(ctx, path.Join(p.prefix, "repodata/repomd.xml"))
	if notFound(err) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	if etag == "" {
		return "", false, errors.New("index has no ETag; cannot publish conditionally")
	}
	var idx index
	if err := xml.Unmarshal(data, &idx); err != nil {
		return "", false, err
	}
	seen := map[string]bool{}
	for _, rec := range idx.Data {
		switch rec.Type {
		case "primary", "filelists", "other":
		// Derived caches are regenerated or omitted. They are not repository policy.
		case "primary_db", "filelists_db", "other_db", "primary_zck", "filelists_zck", "other_zck":
			continue
		default:
			return "", false, fmt.Errorf("unsupported metadata %q; refusing to discard it", rec.Type)
		}
		if seen[rec.Type] {
			return "", false, fmt.Errorf("duplicate metadata type %s", rec.Type)
		}
		seen[rec.Type] = true
		href := rec.Location.Href
		if !strings.HasPrefix(href, "repodata/") || path.Clean(href) != href || strings.ContainsAny(href, ":\\?#") {
			return "", false, fmt.Errorf("unsafe metadata path %q", href)
		}
		blob, _, err := p.get(ctx, path.Join(p.prefix, href))
		if err != nil {
			return "", false, err
		}
		sum := sha256.Sum256(blob)
		if rec.Checksum.Type != "sha256" || hex.EncodeToString(sum[:]) != strings.TrimSpace(rec.Checksum.Value) {
			return "", false, fmt.Errorf("unsupported or incorrect checksum for %s", href)
		}
		local := filepath.Join(dir, filepath.FromSlash(href))
		if err := os.MkdirAll(filepath.Dir(local), 0700); err != nil {
			return "", false, err
		}
		if err := os.WriteFile(local, blob, 0600); err != nil {
			return "", false, err
		}
	}
	for _, kind := range []string{"primary", "filelists", "other"} {
		if !seen[kind] {
			return "", false, fmt.Errorf("missing %s metadata", kind)
		}
	}
	if err := os.WriteFile(filepath.Join(dir, "repodata/repomd.xml"), data, 0600); err != nil {
		return "", false, err
	}
	return etag, true, nil
}

func (p publisher) get(ctx context.Context, key string) ([]byte, string, error) {
	result, err := p.client.GetObject(ctx, &s3.GetObjectInput{Bucket: &p.bucket, Key: &key})
	if err != nil {
		return nil, "", err
	}
	defer result.Body.Close()
	data, err := io.ReadAll(result.Body)
	log.Printf("GET %s (%d bytes)", key, len(data))
	return data, aws.ToString(result.ETag), err
}

func (p publisher) putFile(ctx context.Context, key, file, etag, absent string) error {
	data, err := os.ReadFile(file)
	if err != nil {
		return err
	}
	cache := immutable
	contentType := "application/octet-stream"
	if strings.HasSuffix(key, "repomd.xml") {
		cache = "no-cache"
		contentType = "application/xml"
	}
	in := &s3.PutObjectInput{Bucket: &p.bucket, Key: &key, Body: bytes.NewReader(data), CacheControl: &cache, ContentType: &contentType}
	if etag != "" {
		in.IfMatch = &etag
	}
	if absent != "" {
		in.IfNoneMatch = &absent
	}
	_, err = p.client.PutObject(ctx, in)
	if err == nil {
		log.Printf("PUT %s (%d bytes)", key, len(data))
	}
	return err
}

func apiCode(err error, codes ...string) bool {
	var api smithy.APIError
	if !errors.As(err, &api) {
		return false
	}
	for _, code := range codes {
		if api.ErrorCode() == code {
			return true
		}
	}
	return false
}
func notFound(err error) bool { return apiCode(err, "NoSuchKey", "NotFound") }
func command(ctx context.Context, name string, args ...string) error {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, name, args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("%s: %w\n%s", name, err, out)
	}
	return nil
}
