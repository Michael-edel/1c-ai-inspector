from app.services.source_retrieval_plan import (
    ensure_full_source_retrieval,
    extract_query_text,
    query_agent_request_is_supported,
)


PUBLISHED_TOOLS = {"read_source", "search_code", "get_object_structure"}
COMPACT_TOOLS = PUBLISHED_TOOLS | {"read_method_source", "get_edt_metadata_summary"}


def test_code_assistant_receives_full_document_module_before_search() -> None:
    request = {
        "text": "Прочитай модуль документа ЗаказКлиента и найди процедуру ОбработкаЗаполнения",
        "retrieval": [{"tool": "search_code", "arguments": {"query": "ОбработкаЗаполнения"}}],
    }

    normalized = ensure_full_source_retrieval(request, "1c_code_assistant", PUBLISHED_TOOLS)

    assert normalized["retrieval"][0] == {
        "tool": "read_source",
        "arguments": {"module": "Документ.ЗаказКлиента.МодульОбъекта"},
    }
    assert normalized["retrieval"][1] == {
        "tool": "search_code",
        "arguments": {"query": "ОбработкаЗаполнения", "mode": "exact", "limit": 50},
    }
    assert request["retrieval"][0]["tool"] == "search_code"


def test_audit_agent_receives_information_register_record_set_module() -> None:
    normalized = ensure_full_source_retrieval(
        {"text": "Проведи аудит регистра сведений ЦеныНоменклатуры"},
        "1c_audit_agent",
        PUBLISHED_TOOLS,
    )

    assert normalized["retrieval"] == [
        {
            "tool": "read_source",
            "arguments": {"module": "РегистрСведений.ЦеныНоменклатуры.МодульНабораЗаписей"},
        }
    ]


def test_audit_agent_preserves_accumulation_register_type() -> None:
    normalized = ensure_full_source_retrieval(
        {"text": "Проведи аудит регистра накопления Продажи"},
        "1c_audit_agent",
        COMPACT_TOOLS,
    )

    assert normalized["retrieval"] == [
        {
            "tool": "read_source",
            "arguments": {"module": "РегистрНакопления.Продажи.МодульНабораЗаписей"},
        },
        {
            "tool": "get_edt_metadata_summary",
            "arguments": {"objectType": "РегистрНакопления", "name": "Продажи"},
        },
    ]


def test_existing_full_source_step_is_not_duplicated() -> None:
    request = {
        "text": "Проверь документ ЗаказКлиента",
        "retrieval": [
            {
                "tool": "read_source",
                "arguments": {"module": "Документ.ЗаказКлиента.МодульОбъекта"},
            }
        ],
    }

    assert ensure_full_source_retrieval(request, "1c_audit_agent", PUBLISHED_TOOLS) is request


def test_query_agent_and_unpublished_source_tool_are_not_changed() -> None:
    request = {"text": "Проверь документ ЗаказКлиента", "retrieval": []}

    assert ensure_full_source_retrieval(request, "1c_query_agent", PUBLISHED_TOOLS) is request
    assert ensure_full_source_retrieval(request, "1c_code_assistant", {"search_code"}) is request


def test_missing_object_or_malformed_plan_is_left_for_normal_validation() -> None:
    no_object = {"text": "Объясни этот код", "retrieval": []}
    malformed = {"text": "Проверь документ ЗаказКлиента", "retrieval": "invalid"}

    assert ensure_full_source_retrieval(no_object, "1c_code_assistant", PUBLISHED_TOOLS) is no_object
    assert ensure_full_source_retrieval(malformed, "1c_code_assistant", PUBLISHED_TOOLS) is malformed


def test_method_only_request_is_normalized_to_exact_search() -> None:
    request = {
        "text": "Объясни, какую бизнес-логику реализует процедура РассчитатьСебестоимость.",
        "retrieval": [
            {"tool": "bsl_syntax_help", "arguments": {"query": "полный русский вопрос"}},
            {"tool": "search_code", "arguments": {"query": "полный русский вопрос", "limit": 5, "mode": "smart"}},
        ],
    }

    normalized = ensure_full_source_retrieval(
        request,
        "1c_code_assistant",
        PUBLISHED_TOOLS | {"bsl_syntax_help"},
    )

    assert normalized["retrieval"] == [
        {"tool": "search_code", "arguments": {"query": "РассчитатьСебестоимость", "limit": 50, "mode": "exact"}},
    ]


def test_method_and_object_use_compact_source_and_metadata() -> None:
    request = {
        "text": "Объясни процедуру ОбработкаЗаполнения документа ЗаказКлиента",
        "retrieval": [
            {"tool": "read_source", "arguments": {"module": "Документ.ЗаказКлиента.МодульОбъекта"}},
            {"tool": "search_code", "arguments": {"query": "полный вопрос"}},
            {"tool": "get_object_structure", "arguments": {"object_type": "Document", "object_name": "ЗаказКлиента"}},
        ],
    }

    normalized = ensure_full_source_retrieval(request, "1c_code_assistant", COMPACT_TOOLS)

    assert normalized["retrieval"] == [
        {
            "tool": "read_method_source",
            "arguments": {
                "module": "Документ.ЗаказКлиента.МодульОбъекта",
                "method": "ОбработкаЗаполнения",
            },
        },
        {"tool": "get_edt_metadata_summary", "arguments": {"objectType": "Документ", "name": "ЗаказКлиента"}},
    ]


def test_query_agent_extracts_only_the_1c_query() -> None:
    request = {
        "text": "Проверь запрос:\n```bsl\nВЫБРАТЬ Номенклатура.Ссылка ИЗ Справочник.Номенклатура КАК Номенклатура\n```",
        "retrieval": [{"tool": "validate_query", "arguments": {"query": "Проверь запрос"}}],
    }

    normalized = ensure_full_source_retrieval(request, "1c_query_agent", PUBLISHED_TOOLS)

    assert extract_query_text(request).startswith("ВЫБРАТЬ Номенклатура.Ссылка")
    assert normalized["retrieval"][0]["arguments"]["query"].startswith("ВЫБРАТЬ Номенклатура.Ссылка")
    assert query_agent_request_is_supported(request) is True
    assert query_agent_request_is_supported({"text": "Объясни процедуру"}) is False
    assert query_agent_request_is_supported({"text": "Помоги выбрать подходящий агент"}) is False
