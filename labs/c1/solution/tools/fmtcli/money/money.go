// Package money formats amounts of money for people to read.
package money

import (
	"fmt"
	"strings"
)

// Format renders an amount in cents for a currency: "USD" gives $1,234.56,
// "EUR" gives EUR 1.234,56. Other currency codes are written before a US-style number.
func Format(currency string, cents int64) string {
	sign := ""
	if cents < 0 {
		sign = "-"
		cents = -cents
	}
	whole, frac := cents/100, cents%100
	switch currency {
	case "USD":
		return fmt.Sprintf("%s$%s.%02d", sign, group(whole, ","), frac)
	case "EUR":
		return fmt.Sprintf("%sEUR %s,%02d", sign, group(whole, "."), frac)
	default:
		return fmt.Sprintf("%s%s %s.%02d", sign, currency, group(whole, ","), frac)
	}
}

// group writes n with sep between each group of three digits: 1234567 -> 1,234,567.
func group(n int64, sep string) string {
	digits := fmt.Sprint(n)
	var parts []string
	for len(digits) > 3 {
		parts = append([]string{digits[len(digits)-3:]}, parts...)
		digits = digits[:len(digits)-3]
	}
	parts = append([]string{digits}, parts...)
	return strings.Join(parts, sep)
}
