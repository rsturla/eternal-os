package main

import "sync"

func main() {
	var value int
	var workers sync.WaitGroup
	for range 2 {
		workers.Go(func() {
			for range 1000 {
				value++
			}
		})
	}
	workers.Wait()
}
