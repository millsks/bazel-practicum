// Package textutil counts lines and words in text.
package textutil

import "strings"

// Words returns the number of whitespace-separated words in s.
func Words(s string) int {
	return len(strings.Fields(s))
}

// Lines returns the number of newline characters in s, like wc -l.
func Lines(s string) int {
	return strings.Count(s, "\n")
}
