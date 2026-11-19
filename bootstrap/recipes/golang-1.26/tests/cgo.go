package main

/*
#include <stdlib.h>
*/
import "C"

import "fmt"

func main() { fmt.Printf("cgo=%d\n", C.abs(-42)) }
