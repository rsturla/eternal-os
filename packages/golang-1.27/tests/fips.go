package main

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"crypto/fips140"
	"crypto/sha256"
	"fmt"
)

func main() {
	block, err := aes.NewCipher(make([]byte, 32))
	if err != nil {
		panic(err)
	}
	aead, err := cipher.NewGCMWithRandomNonce(block)
	if err != nil {
		panic(err)
	}
	message := []byte("rpmx authenticated encryption")
	sealed := aead.Seal(nil, nil, message, []byte("context"))
	opened, err := aead.Open(nil, nil, sealed, []byte("context"))
	if err != nil || !bytes.Equal(opened, message) {
		panic("AES-GCM round trip failed")
	}
	sealed[len(sealed)-1] ^= 1
	if _, err := aead.Open(nil, nil, sealed, []byte("context")); err == nil {
		panic("AES-GCM accepted a corrupted authentication tag")
	}
	fmt.Printf("enabled=%t sha256=%x aead=ok\n", fips140.Enabled(), sha256.Sum256([]byte("abc")))
}
