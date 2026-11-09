package main

import (
	"fmt"

	"example.com/harbor/tools/fmtcli/money"
)

func main() {
	fmt.Println(money.Format("USD", 100))
}
