package probe

func Sum[T ~int | ~int64](values []T) T {
	var sum T
	for _, value := range values {
		sum += value
	}
	return sum
}
