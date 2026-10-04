module github.com/jackmaiorino/spellbench/engines/gorge

go 1.25.8

require (
	github.com/adams-shaun/gorge v0.0.0-20260927030508-26257e0eda17
	github.com/adams-shaun/gorge/spellbench-strategies v0.0.0
	golang.org/x/text v0.37.0
)

replace github.com/adams-shaun/gorge/spellbench-strategies => ./strategies
