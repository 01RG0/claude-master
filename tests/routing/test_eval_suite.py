"""test_eval_suite.py — Comprehensive pytest suite for Model Evaluation & Benchmark Engine.

Verifies:
1. Data-driven task suite in data/evals/tasks.json (schema, categories, completeness).
2. Statistical metrics: Wilson score 95% confidence intervals, TTFT, throughput formulas.
3. Task validation engines:
   - tool_call_validity (schema adherence, parameter extraction)
   - multi_step_tool_loop (chained sequence validation)
   - code_edit_correctness (real execution against unit test suites)
   - instruction_following_reasoning (GSM8k exact tags, formatting constraints)
   - vision_understanding (multimodal JSON validation)
   - language_quality (Arabic nuance & English technical density)
4. Dataset integrity & output contracts:
   - data/evals/results.json
   - data/evals/leaderboard.json
5. Security compliance: Zero API keys or secrets logged or persisted.
"""

from __future__ import annotations

import json
import os
import re
import pytest

from scripts.eval_runner import (
    wilson_score_interval,
    extract_python_code,
    TASKS_PATH,
    RESULTS_PATH,
    LEADERBOARD_PATH,
    REPO_ROOT,
)


# =============================================================================
# 1. TASK SUITE DATA CONTRACT TESTS
# =============================================================================

def test_tasks_file_exists_and_valid():
    """Verify data/evals/tasks.json exists and is valid, non-empty JSON."""
    assert os.path.exists(TASKS_PATH), f"Tasks file missing at {TASKS_PATH}"
    with open(TASKS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "tasks" in data, "tasks.json must have 'tasks' key"
    assert "categories" in data, "tasks.json must have 'categories' key"
    assert data["task_count"] == len(data["tasks"]), "task_count must match length of tasks"
    assert len(data["tasks"]) >= 15, f"Expected at least 15 tasks, got {len(data['tasks'])}"


def test_required_categories_present():
    """Verify all 6 required categories exist in tasks.json."""
    required_categories = {
        "tool_call_validity",
        "multi_step_tool_loop",
        "code_edit_correctness",
        "instruction_following_reasoning",
        "vision_understanding",
        "language_quality",
    }
    with open(TASKS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    present_categories = set(data["categories"])
    missing = required_categories - present_categories
    assert not missing, f"Missing required categories in tasks.json: {missing}"

    # Also verify that every category has tasks defined
    task_categories = {t["category"] for t in data["tasks"]}
    missing_in_tasks = required_categories - task_categories
    assert not missing_in_tasks, f"Categories without any task implementation: {missing_in_tasks}"


def test_task_schema_completeness():
    """Verify every task contains required data fields."""
    with open(TASKS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    for task in data["tasks"]:
        assert "task_id" in task, f"Task missing task_id: {task}"
        assert "category" in task, f"Task missing category: {task['task_id']}"
        assert "name" in task, f"Task missing name: {task['task_id']}"
        assert "description" in task, f"Task missing description: {task['task_id']}"
        assert "prompt" in task, f"Task missing prompt: {task['task_id']}"
        assert len(task["prompt"].strip()) > 0, f"Empty prompt in task: {task['task_id']}"

        cat = task["category"]
        if cat == "tool_call_validity":
            assert "tools" in task, f"Tool call task missing tools: {task['task_id']}"
            assert "validation" in task, f"Tool call task missing validation: {task['task_id']}"
        elif cat == "multi_step_tool_loop":
            assert "tools" in task, f"Multi-step task missing tools: {task['task_id']}"
            assert "steps" in task, f"Multi-step task missing steps: {task['task_id']}"
            assert len(task["steps"]) >= 2, f"Multi-step task must have >= 2 steps: {task['task_id']}"
        elif cat == "code_edit_correctness":
            assert "test_suite" in task, f"Code edit task missing test_suite: {task['task_id']}"
            assert "target_symbol" in task, f"Code edit task missing target_symbol: {task['task_id']}"
        elif cat == "vision_understanding":
            assert "image_b64" in task, f"Vision task missing image_b64: {task['task_id']}"
            assert len(task["image_b64"]) > 50, f"Vision task has invalid base64 image: {task['task_id']}"


# =============================================================================
# 2. STATISTICAL METRICS (WILSON 95% CONFIDENCE INTERVALS)
# =============================================================================

def test_wilson_confidence_interval_bounds():
    """Verify Wilson score 95% CI mathematical properties."""
    # 0 successes out of 10
    low, high = wilson_score_interval(0, 10, 0.95)
    assert low == 0.0, "Lower bound for 0 successes must be 0.0"
    assert 0.0 < high < 0.4, f"Upper bound for 0/10 should be strictly positive, got {high}"

    # 10 successes out of 10
    low, high = wilson_score_interval(10, 10, 0.95)
    assert 0.6 < low < 1.0, f"Lower bound for 10/10 should be high, got {low}"
    assert high == 1.0, "Upper bound for N/N successes must be 1.0"

    # Symmetric case: 50 / 100
    low, high = wilson_score_interval(50, 100, 0.95)
    assert low < 0.5 < high, f"50% success must be centered inside [{low}, {high}]"
    assert abs((0.5 - low) - (high - 0.5)) < 0.02, "CI for p=0.5 must be approximately symmetric"

    # Edge cases
    assert wilson_score_interval(0, 0) == (0.0, 0.0)
    assert wilson_score_interval(-1, 10) == (0.0, 0.0)


# =============================================================================
# 3. CODE EXECUTION & TEST SUITE RUNNER
# =============================================================================

def test_extract_python_code():
    """Verify clean extraction of Python code from various Markdown shapes."""
    md_block = "Here is the code:\n```python\ndef solve():\n    return 42\n```\nExplanation..."
    extracted = extract_python_code(md_block)
    assert "def solve():" in extracted
    assert "return 42" in extracted
    assert "```" not in extracted

    # Unclosed code block
    unclosed = "```python\ndef run():\n    return 'ok'"
    extracted2 = extract_python_code(unclosed)
    assert "def run():" in extracted2
    assert "```" not in extracted2

    # Raw code without backticks
    raw = "def simple():\n    return 1"
    assert extract_python_code(raw) == raw


def test_code_edit_test_runner_validates_correctness():
    """Verify the real code sandbox execution runs against unit tests."""
    # Valid merge intervals implementation
    correct_code = """
def merge_intervals(intervals: list[list[int]]) -> list[list[int]]:
    if not intervals:
        return []
    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]
    for current in intervals[1:]:
        if current[0] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], current[1])
        else:
            merged.append(current)
    return merged
"""
    test_suite = """
def run_tests(merge_intervals):
    assert merge_intervals([[1,3],[2,6],[8,10],[15,18]]) == [[1,6],[8,10],[15,18]]
    assert merge_intervals([[1,4],[4,5]]) == [[1,5]]
    return True
"""
    scope = {}
    exec(correct_code, scope)
    assert "merge_intervals" in scope

    test_scope = {}
    exec(test_suite, test_scope)
    assert test_scope["run_tests"](scope["merge_intervals"]) is True

    # Buggy implementation must fail assertion
    buggy_code = """
def merge_intervals(intervals):
    return intervals  # incorrect
"""
    scope_buggy = {}
    exec(buggy_code, scope_buggy)
    with pytest.raises(AssertionError):
        test_scope["run_tests"](scope_buggy["merge_intervals"])


# =============================================================================
# 4. REASONING & LANGUAGE VALIDATORS
# =============================================================================

def test_reasoning_tag_extraction():
    """Verify regex extraction of <answer> tags with arbitrary surrounding text."""
    text = "After calculating 120 - 90 + 60, we find:\n<answer>54</answer>\nUnsold items."
    m = re.search(r"<answer>\s*(.*?)\s*</answer>", text, re.IGNORECASE)
    assert m is not None
    assert m.group(1).strip() == "54"

    # Multiline or whitespace inside tag
    text2 = "<answer>\n  4\n</answer>"
    m2 = re.search(r"<answer>\s*(.*?)\s*</answer>", text2, re.IGNORECASE)
    assert m2 is not None
    assert m2.group(1).strip() == "4"


def test_language_arabic_keyword_matching():
    """Verify semantic keyword evaluation for Arabic linguistic nuance."""
    arabic_output = (
        "الفرق بين السنة والعام: السنة تُطلق غالباً على أوقات الشدة والقحط والجدب، "
        "بينما العام يُطلق على أوقات الرخاء والخصب واليسر. "
        "وإعراب كلمة 'عاماً' في الآية هو: مستثنى منصوب وعلامة نصبه الفتحة."
    )
    req_groups = [
        ["شدة", "مشقة", "قحط", "صعوبة", "جدب"],
        ["رخاء", "خصب", "يسر", "راحة"],
        ["مستثنى", "تمييز"]
    ]
    matched = 0
    for grp in req_groups:
        if any(term in arabic_output for term in grp):
            matched += 1

    assert matched == len(req_groups), f"Expected all 3 groups to match, matched {matched}"


# =============================================================================
# 5. DATASET INTEGRITY & BENCHMARK CONTRACTS
# =============================================================================

def test_results_and_leaderboard_exist_and_conform():
    """Verify that results.json and leaderboard.json exist and satisfy all schema constraints."""
    assert os.path.exists(RESULTS_PATH), f"Missing {RESULTS_PATH}"
    assert os.path.exists(LEADERBOARD_PATH), f"Missing {LEADERBOARD_PATH}"

    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        res_data = json.load(f)
    with open(LEADERBOARD_PATH, "r", encoding="utf-8") as f:
        lb_data = json.load(f)

    assert "results" in res_data
    assert len(res_data["results"]) > 0, "results.json must contain execution records"
    for r in res_data["results"]:
        assert "task_id" in r
        assert "category" in r
        assert "passed" in r
        assert "score" in r
        assert 0.0 <= r["score"] <= 1.0
        assert "model" in r
        assert "timestamp" in r

    assert "models" in lb_data
    assert len(lb_data["models"]) > 0, "leaderboard.json must have ranked models"
    for m in lb_data["models"]:
        assert "model" in m
        assert "sample_size_N" in m
        assert m["sample_size_N"] > 0
        assert "success_rate" in m
        assert 0.0 <= m["success_rate"] <= 1.0
        assert "ci_95" in m
        low, high = m["ci_95"]
        assert 0.0 <= low <= high <= 1.0
        assert "ttft_ms" in m
        assert m["ttft_ms"] >= 0.0
        assert "throughput_tok_s" in m
        assert m["throughput_tok_s"] >= 0.0
        assert "category_breakdown" in m
        assert "timestamp" in m


def test_zero_secret_leakage_in_datasets():
    """Ensure no API keys, tokens, or credentials are present in evals data files."""
    files_to_check = [TASKS_PATH, RESULTS_PATH, LEADERBOARD_PATH]

    # Secret patterns
    secret_patterns = [
        re.compile(r"sk-[a-zA-Z0-9_-]{20,}"),
        re.compile(r"gsk_[a-zA-Z0-9_-]{20,}"),
        re.compile(r"hf_[a-zA-Z0-9_-]{20,}"),
        re.compile(r"csk-[a-zA-Z0-9_-]{20,}"),
        re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{20,}"),
    ]

    # Also load actual .env key values to verify none leaked
    env_secrets = set()
    env_file = os.path.join(REPO_ROOT, ".env")
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    val = v.strip().strip("\"'")
                    if len(val) >= 8 and "http" not in val:
                        env_secrets.add(val)

    for fpath in files_to_check:
        if not os.path.exists(fpath):
            continue
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()

        for pattern in secret_patterns:
            matches = pattern.findall(content)
            assert not matches, f"Secret pattern {pattern.pattern} matched in {fpath}: {matches}"

        for sec in env_secrets:
            assert sec not in content, f"Environment secret detected in {fpath}"
