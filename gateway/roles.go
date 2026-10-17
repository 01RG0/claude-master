// roles.go — model aliases + role mapping.
//
// Claude Code sends Claude names (claude-*, opus/sonnet/haiku/fable aliases,
// dated snapshots). The gateway must map EVERYTHING to a configured model and
// never 422 on a name. Precedence: exact model id → model_aliases → role
// default (roles.main) → first configured model. Overrides always win.
package gateway

import "strings"

// RoleMapping maps task roles to upstream "provider/model" or bare model ids.
type RoleMapping struct {
	Main       string `json:"main,omitempty"`
	Fast       string `json:"fast,omitempty"`
	Subagent   string `json:"subagent,omitempty"`
	Vision     string `json:"vision,omitempty"`
	Summarizer string `json:"summarizer,omitempty"`
}

// ResolveModel maps a requested model name to an upstream model id.
// requested may be "provider/model", a bare id, a Claude name, or an alias.
// It never returns "" when candidates is non-empty.
func ResolveModel(requested string, aliases map[string]string, roles *RoleMapping, candidates []string) string {
	if len(candidates) == 0 {
		return requested
	}
	// 1. Exact match (case-insensitive) against configured models.
	for _, c := range candidates {
		if strings.EqualFold(c, requested) || strings.EqualFold(providerModelSuffix(c), requested) {
			return c
		}
	}
	// 2. Explicit alias table.
	if aliases != nil {
		if v, ok := aliases[requested]; ok && v != "" {
			return firstExisting([]string{v}, candidates)
		}
		lower := strings.ToLower(requested)
		for k, v := range aliases {
			if strings.ToLower(k) == lower && v != "" {
				return firstExisting([]string{v}, candidates)
			}
		}
	}
	// 3. Built-in Claude family mapping → roles.
	if roles != nil {
		if m := roleForClaudeName(requested, roles); m != "" {
			if r := firstExisting([]string{m}, candidates); r != "" {
				return r
			}
		}
	}
	// 4. Role default (if configured)
	if roles != nil && roles.Main != "" {
		if r := firstExisting([]string{roles.Main}, candidates); r != "" {
			return r
		}
	}
	// 5. Dynamic resolution for Claude names / roles when not explicitly overridden
	if dyn := DynamicRoleCandidate(requested, candidates); dyn != "" {
		return dyn
	}
	return candidates[0]
}

func providerModelSuffix(c string) string {
	if i := strings.Index(c, "/"); i >= 0 {
		return c[i+1:]
	}
	return c
}

func firstExisting(want []string, candidates []string) string {
	for _, w := range want {
		for _, c := range candidates {
			if strings.EqualFold(c, w) || strings.EqualFold(providerModelSuffix(c), w) {
				return c
			}
		}
	}
	return ""
}

// roleForClaudeName maps Claude families/aliases to a role model id.
func roleForClaudeName(name string, roles *RoleMapping) string {
	if roles == nil {
		return ""
	}
	n := strings.ToLower(name)
	isClaude := strings.Contains(n, "claude") || n == "opus" || n == "sonnet" ||
		n == "haiku" || n == "fable" || strings.HasPrefix(n, "opus") ||
		strings.HasPrefix(n, "sonnet") || strings.HasPrefix(n, "haiku")
	if !isClaude {
		return ""
	}
	// Fast family → fast role; everything else → main (subagents inherit).
	if strings.Contains(n, "haiku") {
		if roles.Fast != "" {
			return roles.Fast
		}
	}
	if roles.Main != "" {
		return roles.Main
	}
	return ""
}

// DynamicRoleCandidate searches candidates for a model best fitting the role or Claude alias.
func DynamicRoleCandidate(roleOrAlias string, candidates []string) string {
	if len(candidates) == 0 {
		return ""
	}
	n := strings.ToLower(roleOrAlias)
	var keywords []string
	switch {
	case strings.Contains(n, "haiku") || n == "fast" || n == "small":
		keywords = []string{"flash", "small", "mini", "8b", "7b", "haiku", "fast"}
	case strings.Contains(n, "opus") || n == "complex_reasoning" || n == "reasoning":
		keywords = []string{"opus", "pro", "plus", "120b", "72b", "70b", "large"}
	case strings.Contains(n, "vision"):
		keywords = []string{"vision", "flash"}
	case strings.Contains(n, "summarizer") || strings.Contains(n, "summary"):
		keywords = []string{"flash", "small", "mini", "8b"}
	case strings.Contains(n, "subagent"):
		keywords = []string{"flash", "instruct", "code"}
	case strings.Contains(n, "sonnet") || n == "main" || strings.Contains(n, "claude") || n == "default" || n == "fable":
		keywords = []string{"sonnet", "ministral", "qwen", "gpt-oss", "flash", "code", "instruct", "27b", "30b"}
	default:
		return ""
	}

	for _, kw := range keywords {
		for _, c := range candidates {
			if strings.Contains(strings.ToLower(c), kw) {
				return c
			}
		}
	}
	return ""
}

// RoleForTask picks a role model for internal routing (summaries, vision).
func RoleForTask(task string, roles *RoleMapping, candidates []string) string {
	if len(candidates) == 0 {
		return ""
	}
	if roles != nil {
		var want string
		switch strings.ToLower(task) {
		case "vision":
			want = roles.Vision
		case "summarize", "summarizer", "fast", "small":
			want = roles.Summarizer
			if want == "" {
				want = roles.Fast
			}
		case "subagent":
			want = roles.Subagent
		default:
			want = roles.Main
		}
		if want != "" {
			if r := firstExisting([]string{want}, candidates); r != "" {
				return r
			}
		}
	}
	// Fall back to dynamic candidate selection
	if dyn := DynamicRoleCandidate(task, candidates); dyn != "" {
		return dyn
	}
	return candidates[0]
}
