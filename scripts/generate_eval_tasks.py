"""generate_eval_tasks.py — Generates data-driven task suite data/evals/tasks.json.

Includes all 6 required categories:
1. tool_call_validity: schema adherence and argument extraction
2. multi_step_tool_loop: multi-step chained tool loops
3. code_edit_correctness: real code replacement tested against real python unit test suites
4. instruction_following_reasoning: GSM8k multi-step math and deductive logic puzzles
5. vision_understanding: UI inspection and chart analysis with base64 visual assets
6. language_quality: Arabic linguistic nuance / syntax and English technical clarity
"""

import base64
import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVALS_DIR = os.path.join(REPO_ROOT, "data", "evals")
ASSETS_DIR = os.path.join(EVALS_DIR, "assets")


def load_b64(filename: str) -> str:
    path = os.path.join(ASSETS_DIR, filename)
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def build_tasks():
    ui_b64 = load_b64("ui_button.png")
    chart_b64 = load_b64("chart_latency.png")
    status_b64 = load_b64("status_grid.png")

    tasks = [
        # =========================================================================
        # 1. TOOL CALL VALIDITY (Schema adherence & argument extraction)
        # =========================================================================
        {
            "task_id": "tool_call_validity_01",
            "category": "tool_call_validity",
            "name": "search_logs_schema_adherence",
            "description": "Verify function calling schema adherence and correct argument extraction for log searching.",
            "prompt": "Find all ERROR logs from 'auth-service' that occurred within the past 2 hours. Limit results to 20.",
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "search_logs",
                        "description": "Search service operational logs with filtering.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "service_name": {
                                    "type": "string",
                                    "description": "Target service identifier"
                                },
                                "min_severity": {
                                    "type": "string",
                                    "enum": ["DEBUG", "INFO", "WARN", "ERROR"],
                                    "description": "Minimum severity level"
                                },
                                "time_range_hours": {
                                    "type": "integer",
                                    "description": "Lookback window in hours"
                                },
                                "limit": {
                                    "type": "integer",
                                    "description": "Maximum entries to return"
                                }
                            },
                            "required": ["service_name", "min_severity"]
                        }
                    }
                }
            ],
            "validation": {
                "type": "tool_call",
                "expected_function": "search_logs",
                "expected_args": {
                    "service_name": "auth-service",
                    "min_severity": "ERROR",
                    "time_range_hours": 2,
                    "limit": 20
                }
            }
        },
        {
            "task_id": "tool_call_validity_02",
            "category": "tool_call_validity",
            "name": "calculate_tax_argument_extraction",
            "description": "Verify precise numeric and enum argument extraction across schema fields.",
            "prompt": "Calculate income tax for a single taxpayer in California with an annual income of $125000 and $12000 in deductions.",
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "calculate_tax",
                        "description": "Calculate state and federal tax estimation.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "income": {
                                    "type": "number",
                                    "description": "Gross annual income in USD"
                                },
                                "state": {
                                    "type": "string",
                                    "description": "Two-letter US state code or state name"
                                },
                                "filing_status": {
                                    "type": "string",
                                    "enum": ["single", "married_joint", "head_of_household"]
                                },
                                "deductions": {
                                    "type": "number",
                                    "description": "Total allowable deductions"
                                }
                            },
                            "required": ["income", "state", "filing_status"]
                        }
                    }
                }
            ],
            "validation": {
                "type": "tool_call",
                "expected_function": "calculate_tax",
                "expected_args": {
                    "income": 125000,
                    "filing_status": "single",
                    "deductions": 12000
                },
                "state_match": ["CA", "California", "california", "ca"]
            }
        },
        {
            "task_id": "tool_call_validity_03",
            "category": "tool_call_validity",
            "name": "nested_filter_schema_validation",
            "description": "Validate extraction of nested object schemas with arrays and type constraints.",
            "prompt": "Schedule an engineering sync titled 'Sprint Retrospective' with attendees ['alice@company.com', 'bob@company.com'] for 45 minutes with recording enabled.",
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "schedule_calendar_event",
                        "description": "Create a calendar event with participants and options.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "attendees": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                },
                                "duration_minutes": {"type": "integer"},
                                "record_session": {"type": "boolean"}
                            },
                            "required": ["title", "attendees", "duration_minutes"]
                        }
                    }
                }
            ],
            "validation": {
                "type": "tool_call",
                "expected_function": "schedule_calendar_event",
                "expected_args": {
                    "title": "Sprint Retrospective",
                    "duration_minutes": 45,
                    "record_session": True
                },
                "attendees_contains": ["alice@company.com", "bob@company.com"]
            }
        },

        # =========================================================================
        # 2. MULTI-STEP TOOL LOOP (Chained tool calling)
        # =========================================================================
        {
            "task_id": "multi_step_tool_loop_01",
            "category": "multi_step_tool_loop",
            "name": "user_quota_audit_chain",
            "description": "Multi-step tool call chain: lookup user ID from email, then query quota and synthesize decision.",
            "prompt": "Check if user 'sarah.connor@cyberdyne.org' has exceeded her storage quota, and report her usage and quota limit.",
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup_user",
                        "description": "Get user account details by email address.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "email": {"type": "string"}
                            },
                            "required": ["email"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "get_storage_quota",
                        "description": "Retrieve current storage metrics by user ID.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "user_id": {"type": "string"}
                            },
                            "required": ["user_id"]
                        }
                    }
                }
            ],
            "steps": [
                {
                    "step_number": 1,
                    "expected_call": "lookup_user",
                    "expected_args": {"email": "sarah.connor@cyberdyne.org"},
                    "mock_response": {"user_id": "usr_9981", "name": "Sarah Connor", "tier": "pro"}
                },
                {
                    "step_number": 2,
                    "expected_call": "get_storage_quota",
                    "expected_args": {"user_id": "usr_9981"},
                    "mock_response": {"used_gb": 42.5, "limit_gb": 50.0, "exceeded": False}
                }
            ],
            "validation": {
                "type": "multi_step",
                "required_tool_sequence": ["lookup_user", "get_storage_quota"],
                "final_answer_must_contain": ["42.5", "50", "not exceeded"]
            }
        },
        {
            "task_id": "multi_step_tool_loop_02",
            "category": "multi_step_tool_loop",
            "name": "incident_root_cause_chain",
            "description": "Multi-step tool call chain: check service status, inspect dependency, and summarize root cause.",
            "prompt": "Investigate why the 'checkout-service' is reporting errors and find the exact bottleneck.",
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "check_service_status",
                        "description": "Inspect service health status and downstream dependencies.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "service": {"type": "string"}
                            },
                            "required": ["service"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "inspect_db_pool",
                        "description": "Get database connection pool metrics.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "cluster_id": {"type": "string"}
                            },
                            "required": ["cluster_id"]
                        }
                    }
                }
            ],
            "steps": [
                {
                    "step_number": 1,
                    "expected_call": "check_service_status",
                    "expected_args": {"service": "checkout-service"},
                    "mock_response": {"status": "degraded", "error": "DB_CONNECTION_TIMEOUT", "dependency": "db-orders-main"}
                },
                {
                    "step_number": 2,
                    "expected_call": "inspect_db_pool",
                    "expected_args": {"cluster_id": "db-orders-main"},
                    "mock_response": {"active_connections": 200, "max_connections": 200, "queued_waiters": 85}
                }
            ],
            "validation": {
                "type": "multi_step",
                "required_tool_sequence": ["check_service_status", "inspect_db_pool"],
                "final_answer_must_contain": ["pool", "connection"]
            }
        },

        # =========================================================================
        # 3. CODE EDIT CORRECTNESS (Passes real Python unit tests)
        # =========================================================================
        {
            "task_id": "code_edit_correctness_01",
            "category": "code_edit_correctness",
            "name": "normalize_url_function",
            "description": "Generate clean Python function to normalize URLs: lowercases scheme and host, removes default ports (80/443), strips trailing slashes on non-root paths, and sorts query parameters.",
            "prompt": (
                "Write a Python function `normalize_url(url: str) -> str` that performs standard URL normalization:\n"
                "1. Lowercase scheme and host (leave path casing intact).\n"
                "2. Remove standard default ports (:80 for http, :443 for https).\n"
                "3. Remove trailing slashes from path unless the path is simply '/'.\n"
                "4. Sort query parameters alphabetically by key. If no query parameters, omit '?'.\n"
                "Output ONLY the python code inside a ```python ``` code block."
            ),
            "test_suite": """
def run_tests(normalize_url):
    assert normalize_url('HTTP://Example.COM:80/path/?b=2&a=1') == 'http://example.com/path?a=1&b=2'
    assert normalize_url('https://MySite.org:443/') == 'https://mysite.org/'
    assert normalize_url('http://test.io/api/v1/') == 'http://test.io/api/v1'
    assert normalize_url('http://alpha.com:8080/deep/dir/?z=9&m=4') == 'http://alpha.com:8080/deep/dir?m=4&z=9'
    assert normalize_url('https://secure.net/page') == 'https://secure.net/page'
    return True
""",
            "target_symbol": "normalize_url"
        },
        {
            "task_id": "code_edit_correctness_02",
            "category": "code_edit_correctness",
            "name": "merge_intervals_algorithm",
            "description": "Implement merge_intervals algorithm in Python passing edge cases and sorted order tests.",
            "prompt": (
                "Write a Python function `merge_intervals(intervals: list[list[int]]) -> list[list[int]]` "
                "that merges all overlapping intervals and returns an array of the non-overlapping intervals in ascending order.\n"
                "Output ONLY the python code inside a ```python ``` code block."
            ),
            "test_suite": """
def run_tests(merge_intervals):
    assert merge_intervals([[1,3],[2,6],[8,10],[15,18]]) == [[1,6],[8,10],[15,18]]
    assert merge_intervals([[1,4],[4,5]]) == [[1,5]]
    assert merge_intervals([[6,8],[1,9],[2,4],[4,7]]) == [[1,9]]
    assert merge_intervals([]) == []
    assert merge_intervals([[1,4]]) == [[1,4]]
    return True
""",
            "target_symbol": "merge_intervals"
        },
        {
            "task_id": "code_edit_correctness_03",
            "category": "code_edit_correctness",
            "name": "token_bucket_rate_limiter",
            "description": "Implement TokenBucket rate limiter class with capacity, refill_rate, and take() method.",
            "prompt": (
                "Implement a Python class `TokenBucket` for rate limiting:\n"
                "```python\n"
                "class TokenBucket:\n"
                "    def __init__(self, capacity: float, refill_rate: float, initial_tokens: float = None):\n"
                "        pass\n"
                "    def consume(self, tokens: float = 1.0, current_time: float = None) -> bool:\n"
                "        pass\n"
                "```\n"
                "`capacity`: maximum bucket capacity.\n"
                "`refill_rate`: tokens added per unit time.\n"
                "`initial_tokens`: initial tokens (defaults to capacity if None).\n"
                "`consume(tokens, current_time)`: returns True if sufficient tokens existed to consume, False otherwise.\n"
                "Output ONLY the python code inside a ```python ``` code block."
            ),
            "test_suite": """
def run_tests(TokenBucket):
    tb = TokenBucket(capacity=10.0, refill_rate=2.0, initial_tokens=5.0)
    assert tb.consume(3.0, current_time=0.0) is True
    assert tb.consume(3.0, current_time=0.0) is False  # only 2 left
    assert tb.consume(4.0, current_time=2.0) is True   # refilled 4 tokens (2 + 4 = 6)
    assert tb.consume(10.0, current_time=2.0) is False
    assert tb.consume(10.0, current_time=100.0) is True # capped at capacity 10
    return True
""",
            "target_symbol": "TokenBucket"
        },

        # =========================================================================
        # 4. INSTRUCTION FOLLOWING & REASONING (GSM8k & Logic)
        # =========================================================================
        {
            "task_id": "reasoning_gsm8k_croissants",
            "category": "instruction_following_reasoning",
            "name": "gsm8k_bakery_inventory_arithmetic",
            "description": "Multi-step arithmetic word problem requiring step-by-step reasoning and exact tag extraction.",
            "prompt": (
                "Solve this math problem step by step:\n"
                "A bakery baked 120 croissants in the morning. They sold 3/4 of them by noon. "
                "In the afternoon, they baked 60 more croissants and sold 40% of their total afternoon stock before closing. "
                "How many croissants remained unsold at the end of the day?\n\n"
                "Show your step-by-step calculation, and place your final numeric answer inside <answer>X</answer>."
            ),
            "validation": {
                "type": "exact_tag",
                "tag": "answer",
                "expected_value": "54",
                "tolerance": 0.01
            }
        },
        {
            "task_id": "reasoning_rack_deduction",
            "category": "instruction_following_reasoning",
            "name": "deductive_server_rack_ordering",
            "description": "5-element ordering puzzle under spatial and negative constraints.",
            "prompt": (
                "Solve the following server rack logic puzzle:\n"
                "Five servers (Alpha, Beta, Gamma, Delta, Epsilon) occupy slots 1 to 5 from top to bottom (slot 1 is top, slot 5 is bottom).\n"
                "1. Alpha is in slot 1.\n"
                "2. Beta is in the slot immediately above Delta.\n"
                "3. Gamma is neither in slot 2 nor in slot 5.\n"
                "4. Epsilon is located in a slot below Delta.\n\n"
                "Determine which slot number Gamma occupies. Explain the logical deduction, and output your final slot number inside <answer>X</answer>."
            ),
            "validation": {
                "type": "exact_tag",
                "tag": "answer",
                "expected_value": "4"
            }
        },
        {
            "task_id": "reasoning_strict_negative_constraints",
            "category": "instruction_following_reasoning",
            "name": "strict_format_and_negative_constraints",
            "description": "Strict compliance with bullet count, word length bounds, and negative vocabulary bans.",
            "prompt": (
                "List exactly 3 best practices for hardening cloud server SSH configurations.\n"
                "Adhere to all of the following rules without exception:\n"
                "1. Output exactly 3 bullet points starting with '* '.\n"
                "2. Each bullet point must be between 5 and 9 words long.\n"
                "3. Do not include the words 'password', 'key', or 'root' in your response.\n"
                "4. Do not include any greeting, intro, or concluding text."
            ),
            "validation": {
                "type": "constrained_text",
                "bullet_prefix": "* ",
                "bullet_count": 3,
                "min_words_per_bullet": 5,
                "max_words_per_bullet": 9,
                "forbidden_words": ["password", "key", "root"]
            }
        },

        # =========================================================================
        # 5. VISION UNDERSTANDING (UI & Chart Inspection)
        # =========================================================================
        {
            "task_id": "vision_ui_button_inspection",
            "category": "vision_understanding",
            "name": "ui_dialog_button_identification",
            "description": "Inspect UI modal image, extract primary action button text and visual color.",
            "prompt": (
                "Inspect this dialog box image. Identify the primary confirmation button label and its dominant color.\n"
                "Respond with a valid JSON object matching this schema:\n"
                "{\"button_label\": string, \"button_color\": string}"
            ),
            "image_b64": ui_b64,
            "media_type": "image/png",
            "validation": {
                "type": "json_fields",
                "fields": {
                    "button_label": ["Deploy Service", "deploy service", "Deploy"],
                    "button_color": ["blue", "Blue", "#1e6ef0", "azure", "navy"]
                }
            }
        },
        {
            "task_id": "vision_chart_latency_inspection",
            "category": "vision_understanding",
            "name": "latency_chart_peak_analysis",
            "description": "Read bar chart image to determine service with highest latency and its numeric value.",
            "prompt": (
                "Inspect the attached service latency p95 bar chart. Identify which service has the highest latency and what its latency value is in milliseconds.\n"
                "Respond with a valid JSON object in this format:\n"
                "{\"service\": string, \"latency_ms\": number}"
            ),
            "image_b64": chart_b64,
            "media_type": "image/png",
            "validation": {
                "type": "json_fields",
                "fields": {
                    "service": ["Search", "search"],
                    "latency_ms": 240
                }
            }
        },
        {
            "task_id": "vision_status_grid_inspection",
            "category": "vision_understanding",
            "name": "cluster_status_grid_counting",
            "description": "Count green healthy indicators versus red failed indicators in status diagram.",
            "prompt": (
                "Inspect the attached cluster health nodes diagram. Count how many nodes are green (healthy) and how many are red (failed).\n"
                "Respond in valid JSON:\n"
                "{\"green_count\": number, \"red_count\": number}"
            ),
            "image_b64": status_b64,
            "media_type": "image/png",
            "validation": {
                "type": "json_fields",
                "fields": {
                    "green_count": 3,
                    "red_count": 1
                }
            }
        },

        # =========================================================================
        # 6. LANGUAGE QUALITY (Arabic linguistic nuance & English technical clarity)
        # =========================================================================
        {
            "task_id": "language_arabic_morphology_nuance",
            "category": "language_quality",
            "name": "arabic_semantic_nuance_and_syntax",
            "description": "Distinguish semantic and rhetorical nuances between السنة and العام in Classical Arabic and provide exact syntactic parsing (إعراب).",
            "prompt": (
                "اشرح باختصار الفرق الدلالي والبلاغي بين كلمتي 'السنة' و'العام' في القرآن الكريم واللغة العربية الفصحى. "
                "ثم بيّن الوجه الإعرابي الصحيح لكلمة 'عاماً' في قوله تعالى: (فَلَبِثَ فِيهِمْ أَلْفَ سَنَةٍ إِلَّا خَمْسِينَ عَامًا). "
                "اكتب إجابة علمية محكمة ودقيقة لغوياً."
            ),
            "validation": {
                "type": "keyword_semantic",
                "required_any_groups": [
                    # Group 1: السنة تدل على الشدة أو المشقة أو القحط
                    ["شدة", "مشقة", "قحط", "صعوبة", "جدب", "كرب"],
                    # Group 2: العام يدل على الرخاء أو الخصب أو اليسر
                    ["رخاء", "خصب", "يسر", "راحة", "نعمة", "سعة"],
                    # Group 3: إعراب عاماً
                    ["مستثنى", "تمييز"]
                ]
            }
        },
        {
            "task_id": "language_arabic_technical_translation",
            "category": "language_quality",
            "name": "arabic_systems_terminology_clarity",
            "description": "Translate complex systems engineering concept into idiomatic, rigorous Arabic without awkward transliterations.",
            "prompt": (
                "ترجم النص الهندسي التالي إلى لغة عربية سليمة ومهنية عالية الدقة:\n"
                "'Zero-copy buffer pooling reduces memory allocation overhead and minimizes CPU cache misses in high-throughput network gateways.'\n"
                "يجب أن تكون الترجمة رصينة، وتستخدم المصطلحات التقنية المعيارية."
            ),
            "validation": {
                "type": "keyword_semantic",
                "required_any_groups": [
                    ["دون نسخ", "بدون نسخ", "صفرية النسخ"],
                    ["مخازن مؤقتة", "التخزين المؤقت"],
                    ["إخفاقات", "فقدان", "misses"],
                    ["بوابات", "شبكية"]
                ]
            }
        },
        {
            "task_id": "language_english_technical_clarity",
            "category": "language_quality",
            "name": "distributed_systems_raft_conciseness",
            "description": "Explain Raft log replication and election safety with dense precision under 120 words without filler.",
            "prompt": (
                "Explain how the Raft consensus algorithm guarantees log consistency and prevents split-brain during leader election. "
                "Maintain high technical density, strict accuracy, and professional engineering clarity. "
                "Do not use conversational filler (e.g. 'Sure!', 'In conclusion'). Stay strictly under 130 words."
            ),
            "validation": {
                "type": "technical_density",
                "max_words": 130,
                "required_concepts": ["quorum", "majority", "term", "log"]
            }
        }
    ]

    dataset = {
        "schema_version": "1.0.0",
        "description": "Empirical model evaluation task suite for universal gateway and agent quality.",
        "categories": [
            "tool_call_validity",
            "multi_step_tool_loop",
            "code_edit_correctness",
            "instruction_following_reasoning",
            "vision_understanding",
            "language_quality"
        ],
        "task_count": len(tasks),
        "tasks": tasks
    }

    out_file = os.path.join(EVALS_DIR, "tasks.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)

    print(f"Successfully generated {len(tasks)} tasks to {out_file}")


if __name__ == "__main__":
    build_tasks()
