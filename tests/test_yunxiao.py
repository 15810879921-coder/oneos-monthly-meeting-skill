import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("collector", Path(__file__).resolve().parents[1]/"skills/oneos-monthly-meeting/scripts/collect_yunxiao.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class CollectionTests(unittest.TestCase):
    def test_calendar_boundaries_and_china_timezone(self):
        bounds = c.month_bounds("2024-02")
        self.assertTrue(c.in_month("2024-02-29", bounds))
        self.assertFalse(c.in_month("2024-03-01", bounds))
        self.assertTrue(c.in_month("2024-01-31T16:00:00Z", bounds))
        self.assertFalse(c.in_month("2024-02-29T16:00:00Z", bounds))
        for month in ("2026-13", "10", "2026-1", "bad"):
            with self.assertRaises(c.CollectionError):
                c.month_bounds(month)

    def test_cross_month_undated_activity_children_and_dedup(self):
        sprints = [
            {"id":"s1", "startDate":"2026-09-20", "endDate":"2026-10-03"},
            {"id":"s2", "gmtCreate":"2026-10-14"},
            {"id":"s3", "gmtCreate":"2026-08-01"},
            {"id":"s4", "gmtCreate":"2026-08-01"},
            {"id":"old", "startDate":"2026-09-01", "endDate":"2026-09-15"}]
        items = [
            {"id":"parent", "sprint":[{"id":"s1"},{"id":"s2"}]},
            {"id":"child", "parentId":"parent", "gmtModified":"2026-10-20"},
            {"id":"old-parent", "sprint":{"id":"s3"}},
            {"id":"active-child", "parentId":"old-parent", "updateStatusAt":"2026-10-10"}]
        result = c.group_project({"id":"p", "name":"ONEOS test"}, sprints, items, c.month_bounds("2026-10"))
        self.assertEqual([s["sprint"]["id"] for s in result["selected_sprints"]], ["s1","s2","s3"])
        self.assertEqual(result["unique_workitem_count"], 4)
        self.assertEqual(result["unattributed_sprints"][0]["id"], "s4")
        self.assertIn("active-child", result["selected_sprints"][2]["monthly_activity_item_ids"])

    def test_pagination_reads_every_page(self):
        calls = []
        def client(op, *args):
            page = args[args.index("--page")+1]
            calls.append(page)
            return [{"id":f"{page}-a"},{"id":f"{page}-b"}] if page < 3 else []
        self.assertEqual(len(c.paged(client,"projex-list-sprints",page_size=2)),4)
        self.assertEqual(calls,[1,2,3])

    def test_partial_error_duplicate_or_schema_change_is_not_complete(self):
        for client in (
            lambda *args: [{"id":"same"},{"id":"same"}],
            lambda *args: {"success":False, "data":[]},
            lambda *args: {"unknown":[]},
        ):
            with self.assertRaises(c.CollectionError):
                c.paged(client,"projex-list-sprints",page_size=2)
        def failed(op, *args):
            if args[args.index("--page")+1] == 2:
                raise c.CollectionError("network unavailable")
            return [{"id":"one"},{"id":"two"}]
        with self.assertRaises(c.CollectionError):
            c.paged(failed,"projex-list-sprints",page_size=2)

    def test_missing_sprint_and_parent_cycle_fail(self):
        for items in ([{"id":"i","sprint":{"id":"missing"}}],
                      [{"id":"a","parentId":"b"},{"id":"b","parentId":"a"}]):
            with self.assertRaises(c.CollectionError):
                c.group_project({"id":"p","name":"test"}, [], items, c.month_bounds("2026-10"))

    def test_scope_discovery_and_all_categories(self):
        calls = []
        def client(op,*args):
            calls.append((op,args))
            if op == "projex-search-projects":
                return [{"id":"a","name":"01_ONEOS"},{"id":"b","name":"10_ONEOS V2"},{"id":"c","name":"Other","customCode":None},{"id":"d","name":None,"customCode":None}]
            return []
        result = c.collect(client, "2026-10")
        self.assertEqual([p["project"]["id"] for p in result["projects"]],["a","b"])
        self.assertTrue(result["collection_complete"])
        self.assertTrue(all(c.CATEGORIES in args for op,args in calls if op == "projex-search-workitems"))

    def test_cli_disallows_writes_and_hides_credentials_on_failure(self):
        with patch.dict(c.os.environ,{"ALIBABA_CLOUD_YUNXIAO_ACCESS_TOKEN":"secret","ALIBABA_CLOUD_YUNXIAO_ORGANIZATION_ID":"org"}), patch.object(c.shutil,"which",return_value="aliyun"):
            cli = c.Cli()
        with self.assertRaises(c.CollectionError):
            cli("projex-update-workitem")
        with patch.object(c.subprocess,"run",return_value=SimpleNamespace(returncode=1,stdout="",stderr="secret")):
            with self.assertRaises(c.CollectionError) as error:
                cli("projex-search-projects")
        self.assertNotIn("secret", str(error.exception))


if __name__ == "__main__":
    unittest.main()
