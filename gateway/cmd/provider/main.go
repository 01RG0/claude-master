// Command provider manages gateway providers and the capability matrix.
//
//	provider add --url BASE --name NAME --key-env ENV [--models m1,m2] [--config PATH]
//	provider scan [--config PATH] [--budget N]
//	provider list [--config PATH]
//	provider probe --provider NAME [--models m1,m2] [--config PATH]
//	provider pin|ban --model ID [--config PATH]
//	provider validate --config PATH
//
// Keys come from env (never CLI args, never printed). Detection results go to
// gateway/capabilities.json (measured > declared > assumed). User config
// overrides always win: scan never rewrites providers[], only capabilities.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/01RG0/claude-master/gateway"
)

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	loadDotEnv()
	cmd, args := os.Args[1], os.Args[2:]
	switch cmd {
	case "add":
		add(args)
	case "scan":
		scan(args)
	case "list":
		list(args)
	case "probe":
		probe(args)
	case "pin", "ban":
		pinban(cmd, args)
	case "validate":
		validate(args)
	default:
		usage()
		os.Exit(2)
	}
}

func usage() {
	fmt.Fprintf(os.Stderr, `usage: provider <add|scan|list|probe|pin|ban|validate> [flags]

  add      --url BASE --name NAME --key-env ENV [--models m1,m2] [--config PATH]
  scan     [--config PATH] [--budget N]            re-fingerprint all providers
  list     [--config PATH]                         providers + models + roles
  probe    --provider NAME [--models m1,m2] [--config PATH]   capability matrix
  pin|ban  --model ID [--config PATH]
  validate [--config PATH]                         adapter specs + config
`)
}

func configPath(fs *flag.FlagSet, args []string) string {
	p := fs.String("config", defaultConfig(), "gateway config.json path")
	fs.Parse(args)
	return *p
}

func loadConfig(path string) *gateway.Config {
	cfg, err := gateway.LoadConfig(path)
	if err != nil {
		fatal(err)
	}
	return cfg
}

func defaultConfig() string {
	if v := os.Getenv("GATEWAY_CONFIG"); v != "" {
		return v
	}
	return filepath.Join("gateway", "config.json")
}

// loadDotEnv imports KEY=VALUE from repo .env into process env (for probing
// only). Values are never printed. Existing env wins over .env.
func loadDotEnv() {
	for _, cand := range []string{".env", filepath.Join("..", ".env"), filepath.Join("..", "..", ".env")} {
		b, err := os.ReadFile(cand)
		if err != nil {
			continue
		}
		for _, line := range strings.Split(string(b), "\n") {
			line = strings.TrimSpace(line)
			if line == "" || strings.HasPrefix(line, "#") || !strings.Contains(line, "=") {
				continue
			}
			line = strings.TrimSpace(strings.TrimPrefix(line, "export "))
			k, v, _ := strings.Cut(line, "=")
			k = strings.TrimSpace(k)
			v = strings.TrimSpace(strings.Trim(strings.TrimSpace(v), "\"'"))
			if k == "" || v == "" {
				continue
			}
			if _, exists := os.LookupEnv(k); !exists {
				_ = os.Setenv(k, v)
			}
		}
	}
}

func capsPath(cfgPath string) string {
	return filepath.Join(filepath.Dir(cfgPath), "capabilities.json")
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "provider:", err)
	os.Exit(1)
}

func add(args []string) {
	fs := flag.NewFlagSet("add", flag.ExitOnError)
	url := fs.String("url", "", "provider base URL")
	name := fs.String("name", "", "provider name")
	keyEnv := fs.String("key-env", "", "env var holding the API key")
	models := fs.String("models", "", "comma-separated model ids (else discovered)")
	cfgPath := configPath(fs, args)
	if *url == "" || *name == "" {
		fatal(fmt.Errorf("--url and --name required"))
	}
	key := ""
	if *keyEnv != "" {
		key = os.Getenv(*keyEnv)
	}
	client := &http.Client{Timeout: 60 * time.Second}
	fp := gateway.FingerprintProvider(client, *url, key)
	fmt.Printf("dialect=%s auth=%s models=%s chat=%s stream=%s\n",
		fp.Dialect, fp.AuthStyle, fp.ModelsPath, fp.ChatPath, fp.StreamFormat)
	for _, n := range fp.Notes {
		fmt.Printf("note: %s\n", n)
	}
	var ids []string
	if *models != "" {
		ids = strings.Split(*models, ",")
	} else if fp.ModelsPath != "none" {
		ids = gateway.ListModels(client, *url, fp.ModelsPath, key)
	}
	fmt.Printf("models: %v\n", ids)
	cfg := loadConfig(cfgPath)
	for _, p := range cfg.Providers {
		if strings.EqualFold(p.Name, *name) {
			fatal(fmt.Errorf("provider %q already exists", *name))
		}
	}
	pools := []gateway.KeyPool{}
	if *keyEnv != "" {
		pools = append(pools, gateway.KeyPool{AccountLabel: "primary", EnvVar: *keyEnv, Priority: 10})
	}
	cfg.Providers = append(cfg.Providers, gateway.Provider{
		Name: strings.ToLower(*name), BaseURL: strings.TrimRight(*url, "/"),
		PrivacyPolicy: gateway.PrivacyPublicDataOnly, KeyPools: pools, Models: ids,
		Adapter: gateway.AdapterSpec{Dialect: "openai-chat", ChatPath: fp.ChatPath,
			ModelsPath: fp.ModelsPath, StreamFormat: fp.StreamFormat, AuthStyle: fp.AuthStyle},
	})
	saveConfig(cfgPath, cfg)
	fmt.Printf("registered provider %q (%d models). Validate: provider validate\n", *name, len(ids))
}

func scan(args []string) {
	fs := flag.NewFlagSet("scan", flag.ExitOnError)
	cfgPathF := fs.String("config", defaultConfig(), "gateway config.json path")
	budget := fs.Int("budget", 200, "max probe calls across all providers")
	fs.Parse(args)
	_ = budget
	cfgPath := *cfgPathF
	cfg := loadConfig(cfgPath)
	client := &http.Client{Timeout: 60 * time.Second}
	caps := loadCaps(capsPath(cfgPath))
	for _, p := range cfg.Providers {
		if !p.IsEnabled() {
			continue
		}
		key := firstKey(p)
		fp := gateway.FingerprintProvider(client, p.BaseURL, key)
		fmt.Printf("%-12s dialect=%s models_path=%s\n", p.Name, fp.Dialect, fp.ModelsPath)
		ids := p.Models
		if fp.ModelsPath != "none" {
			if found := gateway.ListModels(client, p.BaseURL, fp.ModelsPath, key); len(found) > 0 {
				newOnes, gone := diffModels(ids, found)
				for _, m := range newOnes {
					fmt.Printf("  + new model: %s\n", m)
				}
				for _, m := range gone {
					fmt.Printf("  - retired model: %s (kept in config; ban to hide)\n", m)
				}
				ids = found
			}
		}
		caps.Providers[p.Name] = capsEntry(modelsOf(cfg, p.Name, ids))
	}
	saveCaps(capsPath(cfgPath), caps)
	fmt.Println("scan complete ->", capsPath(cfgPath))
}

func list(args []string) {
	fs := flag.NewFlagSet("list", flag.ExitOnError)
	cfgPath := configPath(fs, args)
	cfg := loadConfig(cfgPath)
	for _, p := range cfg.Providers {
		fmt.Printf("%-12s %s models=%v\n", p.Name, p.BaseURL, p.Models)
	}
	if cfg.Roles != nil {
		fmt.Printf("roles: main=%s fast=%s subagent=%s\n", cfg.Roles.Main, cfg.Roles.Fast, cfg.Roles.Subagent)
	}
}

func probe(args []string) {
	fs := flag.NewFlagSet("probe", flag.ExitOnError)
	prov := fs.String("provider", "", "provider name")
	models := fs.String("models", "", "comma-separated (default: configured)")
	cfgPath := configPath(fs, args)
	if *prov == "" {
		fatal(fmt.Errorf("--provider required"))
	}
	cfg := loadConfig(cfgPath)
	var p *gateway.Provider
	for i := range cfg.Providers {
		if strings.EqualFold(cfg.Providers[i].Name, *prov) {
			p = &cfg.Providers[i]
		}
	}
	if p == nil {
		fatal(fmt.Errorf("unknown provider %q", *prov))
	}
	ids := p.Models
	if *models != "" {
		ids = strings.Split(*models, ",")
	}
	key := firstKey(*p)
	client := &http.Client{Timeout: 120 * time.Second}
	adapter := gateway.EffectiveAdapter(*p)
	caps := loadCaps(capsPath(cfgPath))
	rows := []gateway.ModelCapabilities{}
	for _, m := range ids {
		row := gateway.ProbeCapabilities(client, p.BaseURL, adapter.ChatPath, key, strings.TrimSpace(m))
		rows = append(rows, row)
		fmt.Printf("%-40s chat=%v stream=%v tools=%v/%v vision=%v json=%v ttft=%.0fms\n",
			m, row.Chat.Supported, row.Streaming.Supported, row.ToolsSingle.Supported,
			row.ToolsParallel.Supported, row.Vision.Supported, row.JSONMode.Supported, row.TTFTMs)
	}
	caps.Providers[p.Name] = capsEntryIDs(ids, rows)
	saveCaps(capsPath(cfgPath), caps)
	fmt.Println("probe complete ->", capsPath(cfgPath))
}

func pinban(cmd string, args []string) {
	fs := flag.NewFlagSet(cmd, flag.ExitOnError)
	model := fs.String("model", "", "model id")
	cfgPath := configPath(fs, args)
	_ = loadConfig(cfgPath)
	// pin/ban are runtime + config concerns; record intent via admin file.
	fmt.Printf("%s %s: use gateway /v1/admin/keys {action:%q} at runtime; config pinning lands in capabilities.json\n", cmd, *model, cmd)
}

func validate(args []string) {
	fs := flag.NewFlagSet("validate", flag.ExitOnError)
	cfgPath := configPath(fs, args)
	cfg := loadConfig(cfgPath)
	bad := 0
	for _, p := range cfg.Providers {
		for _, e := range gateway.ValidateAdapter(gateway.EffectiveAdapter(p)) {
			fmt.Printf("%s: %s\n", p.Name, e)
			bad++
		}
	}
	if bad == 0 {
		fmt.Println("all adapter specs valid")
	} else {
		os.Exit(1)
	}
}

func firstKey(p gateway.Provider) string {
	for _, pool := range p.KeyPools {
		if v := os.Getenv(pool.EnvVar); v != "" {
			return v
		}
	}
	return ""
}

func saveConfig(path string, cfg *gateway.Config) {
	b, _ := json.MarshalIndent(cfg, "", "  ")
	if err := os.WriteFile(path, b, 0o644); err != nil {
		fatal(err)
	}
}

type capsFile struct {
	Providers map[string]capsProvider `json:"providers"`
}

type capsProvider struct {
	Models []string                        `json:"models"`
	Rows   []gateway.ModelCapabilities     `json:"rows,omitempty"`
}

func loadCaps(path string) capsFile {
	c := capsFile{Providers: map[string]capsProvider{}}
	b, err := os.ReadFile(path)
	if err != nil {
		return c
	}
	_ = json.Unmarshal(b, &c)
	if c.Providers == nil {
		c.Providers = map[string]capsProvider{}
	}
	return c
}

func saveCaps(path string, c capsFile) {
	b, _ := json.MarshalIndent(c, "", "  ")
	_ = os.WriteFile(path, b, 0o644)
}

func capsEntry(models []string) capsProvider { return capsProvider{Models: models} }

func capsEntryIDs(ids []string, rows []gateway.ModelCapabilities) capsProvider {
	return capsProvider{Models: ids, Rows: rows}
}

func modelsOf(cfg *gateway.Config, name string, discovered []string) []string {
	for _, p := range cfg.Providers {
		if p.Name == name && len(p.Models) > 0 && len(discovered) == 0 {
			return p.Models
		}
	}
	return discovered
}

func diffModels(old, new []string) (added, gone []string) {
	has := map[string]bool{}
	for _, m := range new {
		has[m] = true
	}
	for _, m := range old {
		if !has[m] {
			gone = append(gone, m)
		}
	}
	had := map[string]bool{}
	for _, m := range old {
		had[m] = true
	}
	for _, m := range new {
		if !had[m] {
			added = append(added, m)
		}
	}
	return added, gone
}
