// hotpath_bench_test.go — Go prototype of the brain hot kernels for ADR-001.
//
// Reimplements the exact Hebbian LTP formula and a spreading-activation BFS
// over an in-memory graph, then benchmarks them with the same workload as
// scripts/bench_brain.py (300 updates / 300 traversals on a 3-node graph).
// Run: go test -run=NONE -bench 'HotPath' -benchtime 300x .
package gateway

import (
	"math"
	"testing"
)

type hotGraph struct {
	w map[string]map[string]float64
}

func newHotGraph() *hotGraph {
	return &hotGraph{w: map[string]map[string]float64{
		"n1": {"n2": 0.5, "n3": 0.3},
		"n2": {"n3": 0.7},
		"n3": {},
	}}
}

// hebbianLTP mirrors brain/learning/hebbian.py HebbianUpdater.ltp:
// w += eta * reward * pre * post * (W_MAX - w), clamped to [0, W_MAX].
func hebbianLTP(g *hotGraph, src, tgt string, eta, reward, pre, post float64) {
	const wMax = 1.0
	w := g.w[src][tgt]
	w += eta * reward * pre * post * (wMax - w)
	if w > wMax {
		w = wMax
	}
	if w < 0 {
		w = 0
	}
	g.w[src][tgt] = w
}

func BenchmarkHotPathHebbian(b *testing.B) {
	g := newHotGraph()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		hebbianLTP(g, "n1", "n2", 0.1, 1.0, 0.8, 0.8)
	}
}

func spreadingGo(g *hotGraph, seeds []string, maxHops int, minWeight float64) map[string]float64 {
	act := map[string]float64{}
	type item struct {
		n string
		a float64
		d int
	}
	queue := []item{}
	for _, s := range seeds {
		queue = append(queue, item{s, 1.0, 0})
	}
	visited := map[string]bool{}
	for len(queue) > 0 {
		cur := queue[0]
		queue = queue[1:]
		if visited[cur.n] || cur.d > maxHops {
			continue
		}
		visited[cur.n] = true
		if cur.d > 0 {
			act[cur.n] += cur.a
		}
		for tgt, w := range g.w[cur.n] {
			if w < minWeight {
				continue
			}
			queue = append(queue, item{tgt, cur.a * w * math.Exp(-0.1*float64(cur.d)), cur.d + 1})
		}
	}
	return act
}

func BenchmarkHotPathSpreading(b *testing.B) {
	g := newHotGraph()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		spreadingGo(g, []string{"n1"}, 2, 0.1)
	}
}
