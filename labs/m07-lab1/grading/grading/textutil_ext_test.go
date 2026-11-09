package grading_test

import (
	"testing"

	"example.com/wordtools/textutil"
)

func TestFromOutside(t *testing.T) {
	text := "the quick brown fox\njumps\n"
	if got := textutil.Words(text); got != 5 {
		t.Errorf("Words = %d, want 5", got)
	}
	if got := textutil.Lines(text); got != 2 {
		t.Errorf("Lines = %d, want 2", got)
	}
}
