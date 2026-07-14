from app.services.source_retrieval_plan import ensure_full_source_retrieval


PUBLISHED_TOOLS = {"read_source", "search_code", "get_object_structure"}


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
    assert normalized["retrieval"][1:] == request["retrieval"]
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
