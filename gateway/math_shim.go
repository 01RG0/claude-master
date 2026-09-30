// math_shim.go provides thin wrappers around standard math functions.
package gateway

import "math"

func mathLog(x float64) float64   { return math.Log(x) }
func mathPow(x, y float64) float64 { return math.Pow(x, y) }
func mathSqrt(x float64) float64  { return math.Sqrt(x) }
