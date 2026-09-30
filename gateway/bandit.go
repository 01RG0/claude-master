// bandit.go — Thompson Sampling model router.
//
// Algorithm ported (concept only, Apache-2.0) from:
//   lm-sys/RouteLLM routellm/routers/routers.py
//
// NOTICE: Clean-room Go reimplementation of the published Beta-bandit formula.
// No source code was copied.
package gateway

import (
	"math/rand"
	"sync"
	"time"
)

// ModelStats holds the Beta posterior parameters for one model.
// Thompson Sampling uses Beta(1+S, 1+F) posteriors from model_stats.
type ModelStats struct {
	ModelID   string
	Successes float64
	Failures  float64
}

func (m *ModelStats) alpha() float64 { return 1 + m.Successes }
func (m *ModelStats) beta() float64  { return 1 + m.Failures }

// ThompsonBandit selects models using Thompson Sampling over Beta posteriors.
type ThompsonBandit struct {
	mu     sync.Mutex
	models map[string]*ModelStats
	rng    *rand.Rand
}

// NewThompsonBandit creates a bandit pre-seeded with the given model IDs.
func NewThompsonBandit(modelIDs []string) *ThompsonBandit {
	b := &ThompsonBandit{
		models: make(map[string]*ModelStats, len(modelIDs)),
		rng:    rand.New(rand.NewSource(time.Now().UnixNano())),
	}
	for _, id := range modelIDs {
		b.models[id] = &ModelStats{ModelID: id}
	}
	return b
}

// SeedStats loads prior successes/failures (e.g. from brain model_stats).
func (b *ThompsonBandit) SeedStats(stats []ModelStats) {
	b.mu.Lock()
	defer b.mu.Unlock()
	for _, s := range stats {
		cp := s
		b.models[s.ModelID] = &cp
	}
}

// SampleModel samples from the Beta posteriors and returns the model with the
// highest sampled value among the given candidates.
func (b *ThompsonBandit) SampleModel(candidates []string) string {
	b.mu.Lock()
	defer b.mu.Unlock()

	bestID := ""
	bestSample := -1.0

	for _, id := range candidates {
		stats, ok := b.models[id]
		if !ok {
			stats = &ModelStats{ModelID: id}
			b.models[id] = stats
		}
		s := betaSample(b.rng, stats.alpha(), stats.beta())
		if s > bestSample {
			bestSample = s
			bestID = id
		}
	}
	return bestID
}

// Update records a success or failure for a model (outcome reporting).
func (b *ThompsonBandit) Update(modelID string, success bool) {
	b.mu.Lock()
	defer b.mu.Unlock()
	stats, ok := b.models[modelID]
	if !ok {
		stats = &ModelStats{ModelID: modelID}
		b.models[modelID] = stats
	}
	if success {
		stats.Successes++
	} else {
		stats.Failures++
	}
}

// Stats returns a copy of the stats for a model (useful in tests).
func (b *ThompsonBandit) Stats(modelID string) (ModelStats, bool) {
	b.mu.Lock()
	defer b.mu.Unlock()
	s, ok := b.models[modelID]
	if !ok {
		return ModelStats{}, false
	}
	return *s, true
}

// betaSample draws a sample from Beta(α, β) via Gamma ratio.
func betaSample(rng *rand.Rand, alpha, beta float64) float64 {
	ga := gammaSample(rng, alpha)
	gb := gammaSample(rng, beta)
	sum := ga + gb
	if sum == 0 {
		return 0.5
	}
	return ga / sum
}

// gammaSample: Marsaglia–Tsang (2000) Gamma(shape, scale=1).
func gammaSample(rng *rand.Rand, shape float64) float64 {
	if shape < 1 {
		u := rng.Float64()
		return gammaSample(rng, shape+1) * mathPow(u, 1.0/shape)
	}
	d := shape - 1.0/3.0
	c := 1.0 / mathSqrt(9.0*d)
	for {
		x := rng.NormFloat64()
		v := 1.0 + c*x
		if v <= 0 {
			continue
		}
		v = v * v * v
		u := rng.Float64()
		if u < 1.0-0.0331*(x*x)*(x*x) {
			return d * v
		}
		if mathLog(u) < 0.5*x*x+d*(1.0-v+mathLog(v)) {
			return d * v
		}
	}
}
