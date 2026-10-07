package agent

import (
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// Inventory against the pinned upstream registry, so a forgotten difficult
// policy cannot disappear from delivery merely because it has no adapter yet.
func TestInventoryCoversEveryShippedPolicy(t *testing.T) {
	var inventory struct {
		GorgeCommit string `json:"gorge_commit"`
		Entries     []struct {
			Key, Name, Integration string
			Upstream               string `json:"upstream_policy"`
		}
	}
	b, err := os.ReadFile("../../../../docs/gorge-roster-20261002.json")
	if err != nil {
		t.Fatal(err)
	}
	if err = json.Unmarshal(b, &inventory); err != nil {
		t.Fatal(err)
	}
	if inventory.GorgeCommit != "26257e0eda1779d739a07e835c6500b9c4dabc62" {
		t.Fatal("inventory pin drift")
	}
	src := os.Getenv("GORGE_SRC")
	if src == "" {
		t.Fatal("GORGE_SRC must identify the pinned source for the inventory audit")
	}
	b, err = os.ReadFile(filepath.Join(src, "cmd", "botbench", "main.go"))
	if err != nil {
		t.Fatal(err)
	}
	registry := strings.SplitN(strings.SplitN(string(b), "var policies =", 2)[1], "func hostedPolicy", 2)[0]
	listed := map[string]bool{}
	byKey := map[string]string{}
	for _, e := range inventory.Entries {
		listed[e.Upstream] = true
		byKey[e.Key] = e.Name
	}
	for _, match := range regexp.MustCompile(`(?m)^\s*"([a-z0-9-]+)":`).FindAllStringSubmatch(registry, -1) {
		if !listed[match[1]] {
			t.Errorf("shipped upstream policy %s is missing", match[1])
		}
	}
	for _, p := range Policies() {
		if byKey[p.Key] != p.Name {
			t.Errorf("adapter identity %s/%s missing from inventory", p.Key, p.Name)
		}
	}
}
