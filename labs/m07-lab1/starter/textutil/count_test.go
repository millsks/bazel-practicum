// An internal test: it is in package textutil, so it calls Words and Lines
// directly. Bazel compiles it together with the library through `embed`.
package textutil

import "testing"

func TestWords(t *testing.T) {
	cases := map[string]int{
		"":                0,
		"one":             1,
		"  two  words \n": 2,
	}
	for in, want := range cases {
		if got := Words(in); got != want {
			t.Errorf("Words(%q) = %d, want %d", in, got, want)
		}
	}
}

func TestLines(t *testing.T) {
	if got := Lines("a\nb\n"); got != 2 {
		t.Errorf("Lines(%q) = %d, want 2", "a\nb\n", got)
	}
}
