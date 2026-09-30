module github.com/01RG0/claude-master

go 1.22

// Root module marker for the monorepo workspace.
// The Anthropic gateway lives in its own module: ./gateway (see gateway/go.mod).
// Run Go tests with: cd gateway && go test ./...
