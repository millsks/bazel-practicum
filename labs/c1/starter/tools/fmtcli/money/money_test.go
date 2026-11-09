package money

import "testing"

func TestFormat(t *testing.T) {
	cases := []struct {
		currency string
		cents    int64
		want     string
	}{
		{"USD", 0, "$0.00"},
		{"USD", 499, "$4.99"},
		{"USD", 123456789, "$1,234,567.89"},
		{"EUR", 99999, "EUR 999,99"},
		{"EUR", 123456, "EUR 1.234,56"},
		{"USD", -75, "-$0.75"},
		{"GBP", 100000, "GBP 1,000.00"},
	}
	for _, c := range cases {
		if got := Format(c.currency, c.cents); got != c.want {
			t.Errorf("Format(%q, %d) = %q, want %q", c.currency, c.cents, got, c.want)
		}
	}
}
