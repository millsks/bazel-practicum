// Command wc counts lines and words.
//
// With arguments, each argument is one line of text:
//
//	wc "to be or" "not to be"   prints   2 lines, 6 words
//
// Without arguments, it reads standard input.
package main

import (
	"fmt"
	"io"
	"os"
	"strings"

	"example.com/wordtools/textutil"
)

func main() {
	var text string
	if len(os.Args) > 1 {
		text = strings.Join(os.Args[1:], "\n") + "\n"
	} else {
		data, err := io.ReadAll(os.Stdin)
		if err != nil {
			fmt.Fprintln(os.Stderr, "wc:", err)
			os.Exit(1)
		}
		text = string(data)
	}
	fmt.Printf("%d lines, %d words\n", textutil.Lines(text), textutil.Words(text))
}
