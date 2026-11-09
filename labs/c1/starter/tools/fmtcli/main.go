// Command fmtcli formats amounts of money, one per line.
//
//	fmtcli USD 499 123456   prints   $4.99
//	                                 $1,234.56
package main

import (
	"fmt"
	"os"
	"strconv"

	"example.com/harbor/tools/fmtcli/money"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: fmtcli CURRENCY CENTS...")
		os.Exit(2)
	}
	currency := os.Args[1]
	for _, arg := range os.Args[2:] {
		cents, err := strconv.ParseInt(arg, 10, 64)
		if err != nil {
			fmt.Fprintf(os.Stderr, "fmtcli: %q is not a whole number of cents\n", arg)
			os.Exit(2)
		}
		fmt.Println(money.Format(currency, cents))
	}
}
