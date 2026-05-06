"""Unit tests for relationship_inference.py.

These are pure-Python tests with no DB dependencies — no mocking needed.
All four confirmed PRMS join rules are verified here.
"""


from app.semantic.relationship_inference import (
    InferredRelationship,
    get_inferred_relationships,
    get_referenced_tables,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ALL_PRMS_TABLES = ["Client", "Project", "Resource", "Status", "BusinessUnit", "Designation"]


# ---------------------------------------------------------------------------
# get_inferred_relationships
# ---------------------------------------------------------------------------


class TestGetInferredRelationships:
    def test_returns_empty_for_empty_selection(self):
        assert get_inferred_relationships([]) == []

    def test_returns_empty_for_unrelated_tables(self):
        result = get_inferred_relationships(["BusinessUnit", "Designation"])
        assert result == []

    def test_client_triggers_one_rule(self):
        result = get_inferred_relationships(["Client"])
        assert len(result) == 1
        rule = result[0]
        assert rule.source_table == "Client"
        assert rule.source_column == "StatusId"
        assert rule.target_table == "Status"
        assert rule.target_column == "StatusId"
        assert rule.filter_hint == "Status.ReferenceId = 1"

    def test_project_triggers_two_rules(self):
        result = get_inferred_relationships(["Project"])
        assert len(result) == 2
        targets = {r.target_table for r in result}
        assert "Status" in targets
        assert "Client" in targets

    def test_resource_triggers_self_join_rule(self):
        result = get_inferred_relationships(["Resource"])
        assert len(result) == 1
        rule = result[0]
        assert rule.source_table == "Resource"
        assert rule.target_table == "Resource"
        assert rule.source_column == "ReportingTo"
        assert rule.target_column == "ResourceId"
        assert rule.filter_hint is None

    def test_all_tables_returns_all_four_rules(self):
        result = get_inferred_relationships(["Client", "Project", "Resource"])
        # Client→Status, Project→Status, Project→Client, Resource→Resource
        assert len(result) == 4

    def test_case_insensitive_table_names(self):
        """Table names coming from the DB may be any case."""
        assert get_inferred_relationships(["client"]) == get_inferred_relationships(["Client"])
        assert get_inferred_relationships(["PROJECT"]) == get_inferred_relationships(["Project"])
        assert get_inferred_relationships(["RESOURCE"]) == get_inferred_relationships(["Resource"])

    def test_status_as_source_returns_no_rule(self):
        """Status is only a *target* in our ruleset, never a source."""
        result = get_inferred_relationships(["Status"])
        assert result == []

    def test_returns_inferred_relationship_instances(self):
        result = get_inferred_relationships(["Client"])
        assert all(isinstance(r, InferredRelationship) for r in result)

    def test_project_status_rule_has_correct_filter(self):
        result = get_inferred_relationships(["Project"])
        status_rules = [r for r in result if r.target_table == "Status"]
        assert len(status_rules) == 1
        assert status_rules[0].filter_hint == "Status.ReferenceId = 2"
        assert status_rules[0].source_column == "ProjectStatusId"

    def test_project_client_rule_has_no_filter(self):
        result = get_inferred_relationships(["Project"])
        client_rules = [r for r in result if r.target_table == "Client"]
        assert len(client_rules) == 1
        assert client_rules[0].filter_hint is None

    def test_all_rules_have_notes(self):
        """Every confirmed rule should have a human-readable note for the LLM."""
        result = get_inferred_relationships(["Client", "Project", "Resource"])
        assert all(r.note is not None and len(r.note) > 10 for r in result)

    def test_duplicate_table_names_handled(self):
        """Passing the same table twice should not duplicate rules."""
        result_once = get_inferred_relationships(["Client"])
        result_twice = get_inferred_relationships(["Client", "Client"])
        assert len(result_once) == len(result_twice)


# ---------------------------------------------------------------------------
# get_referenced_tables
# ---------------------------------------------------------------------------


class TestGetReferencedTables:
    def test_returns_empty_for_empty_selection(self):
        assert get_referenced_tables([]) == []

    def test_returns_empty_for_unrelated_tables(self):
        assert get_referenced_tables(["BusinessUnit"]) == []

    def test_client_needs_status(self):
        missing = get_referenced_tables(["Client"])
        assert "Status" in missing

    def test_project_needs_status_and_client(self):
        missing = get_referenced_tables(["Project"])
        assert "Status" in missing
        assert "Client" in missing

    def test_resource_self_join_not_in_missing(self):
        """Self-joins should never report the table as missing from itself."""
        missing = get_referenced_tables(["Resource"])
        assert "Resource" not in missing

    def test_already_selected_targets_not_in_missing(self):
        """If Status is already selected, it should not appear in missing."""
        missing = get_referenced_tables(["Client", "Status"])
        assert "Status" not in missing

    def test_all_tables_selected_returns_empty(self):
        missing = get_referenced_tables(["Client", "Project", "Resource", "Status"])
        assert missing == []

    def test_no_duplicates_in_output(self):
        """Project and Client both pull in Status — should appear only once."""
        missing = get_referenced_tables(["Project"])
        assert missing.count("Status") == 1

    def test_case_insensitive(self):
        missing_lower = get_referenced_tables(["client"])
        missing_upper = get_referenced_tables(["Client"])
        assert set(missing_lower) == set(missing_upper)

    def test_returns_list_of_strings(self):
        missing = get_referenced_tables(["Client"])
        assert isinstance(missing, list)
        assert all(isinstance(t, str) for t in missing)
