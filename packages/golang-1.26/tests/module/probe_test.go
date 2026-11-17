package probe

import (
	"compress/gzip"
	"errors"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"testing"
)

func TestAlgorithms(t *testing.T) {
	values := []int{3, 1, 2}
	cloned := slices.Clone(values)
	slices.Sort(cloned)
	if !slices.Equal(cloned, []int{1, 2, 3}) || !slices.Equal(values, []int{3, 1, 2}) {
		t.Fatalf("sort/clone result: sorted=%v original=%v", cloned, values)
	}
	if got := Sum([]int64{7, 14, 21}); got != 42 {
		t.Fatalf("generic sum=%d, want 42", got)
	}
}

func TestCompressionErrors(t *testing.T) {
	if _, err := gzip.NewReader(strings.NewReader("invalid gzip header")); !errors.Is(err, gzip.ErrHeader) {
		t.Fatalf("malformed gzip error=%v, want gzip.ErrHeader", err)
	}
}

func TestFilesystem(t *testing.T) {
	path := filepath.Join(t.TempDir(), "payload")
	if err := os.WriteFile(path, []byte("file-bytes"), 0o600); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil || string(data) != "file-bytes" {
		t.Fatalf("read=%q error=%v", data, err)
	}
	if _, err := os.ReadFile(path + ".missing"); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("missing file error=%v, want os.ErrNotExist", err)
	}
}

func TestConcurrency(t *testing.T) {
	results := make(chan int, 3)
	var workers sync.WaitGroup
	for _, value := range []int{7, 14, 21} {
		workers.Go(func() { results <- value })
	}
	workers.Wait()
	close(results)
	var sum int
	for value := range results {
		sum += value
	}
	if sum != 42 {
		t.Fatalf("goroutine/channel sum=%d, want 42", sum)
	}
}
