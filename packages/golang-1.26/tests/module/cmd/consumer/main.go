package main

import (
	"fmt"
	"slices"

	probe "example.invalid/rpmx-probe"
)

func main() {
	values := []int{3, 1, 2}
	slices.Sort(values)
	fmt.Printf("answer=%d sorted=%v\n", probe.Sum([]int{7, 14, 21}), values)
}
