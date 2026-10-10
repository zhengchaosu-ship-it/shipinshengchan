"""单任务核验回归，不连接桌面、不打开素材、不提交。"""
import copy
import unittest
from datetime import datetime, timedelta

from xiaovcat_adapter.desktop_worker.v04_precheck import verify_evidence, read_bound_topics


class PrecheckTests(unittest.TestCase):
    def setUp(self):
        def node(rid, kind, name="", aid="", parent=None):
            return dict(runtime_id=rid, parent_id=parent, control_type=kind, name=name,
                        automation_id=aid, password=False, offscreen=False, enabled=True)
        self.policy = dict(max_jobs=1, max_final_submit_invocations=1, schedule_delay_minutes=130,
                           video_path="ORIGINAL.mp4")
        self.account = dict(accounts=[dict(account_name="丙曜", platform="抖音", online=True,
                                          enabled=True, selected=True)])
        nodes = [node("p", 50033, "丙曜 close")]
        values = {}
        for aid, value in (("title", ""), ("item_title", ""), ("desc", "陶老师小妙招"), ("text", "陶老师小妙招")):
            nodes.append(node(aid, 50004, aid=aid, parent="p"))
            values[aid] = value
        nodes.extend(node(t, 50020, name=t, parent="p") for t in ("健康", "健康科普", "养生"))
        self.text = dict(nodes=nodes, values=values)
        base = datetime.now().astimezone().replace(second=0, microsecond=0)
        scheduled = base + timedelta(minutes=130)
        date = scheduled.strftime("%Y-%m-%d %H:%M")
        self.preview = dict(base_local_time=base.isoformat(), scheduled_at=scheduled.isoformat(), ui_input=date)
        self.timing = dict(nodes=[node("date1", 50004, "请选择日期时间"),
                                 node("date2", 50004, "请选择日期时间"),
                                 node("radio1", 50013, "定时发布"), node("radio2", 50013, "定时发布"),
                                 node("fallback", 50002, "超时后改为即时发布"),
                                 node("submit", 50000, "一键分发")],
                           values={"date1": date, "date2": date},
                           radio_selected={"radio1": True, "radio2": True},
                           checkbox_selected={"fallback": 0})
        self.selection = dict(video_path="ORIGINAL.mp4", file_dialog_value_readback="ORIGINAL.mp4")
        self.prior = dict(submit_attempted=False, final_submit_invocations=0)

    def verify(self):
        return verify_evidence(self.policy, self.account, self.text, self.timing,
                               self.preview, self.selection, self.prior)

    def test_empty_title_and_exact_fields_pass(self):
        self.assertEqual(self.verify()["account_name"], "丙曜")

    def test_never_accept_two_jobs(self):
        self.policy["max_jobs"] = 2
        with self.assertRaises(ValueError): self.verify()

    def test_no_substitution_account(self):
        self.account["accounts"][0]["account_name"] = "其它账号"
        with self.assertRaises(ValueError): self.verify()

    def test_no_offline_account(self):
        self.account["accounts"][0]["online"] = False
        with self.assertRaises(ValueError): self.verify()

    def test_no_generated_title(self):
        self.text["values"]["item_title"] = "文件名"
        with self.assertRaises(ValueError): self.verify()

    def test_exact_description_only(self):
        self.text["values"]["text"] += "#健康"
        with self.assertRaises(ValueError): self.verify()

    def test_actual_topic_chips_required(self):
        self.text["nodes"] = [r for r in self.text["nodes"] if r["name"] != "养生"]
        with self.assertRaises(ValueError): self.verify()

    def test_schedule_readback_both_sides_required(self):
        self.timing["values"]["date2"] = "wrong"
        with self.assertRaises(ValueError): self.verify()

    def test_no_repeat_after_uncertain_submit(self):
        self.prior["submit_attempted"] = True
        with self.assertRaises(ValueError): self.verify()

    def test_no_immediate_fallback(self):
        self.timing["checkbox_selected"]["fallback"] = 1
        with self.assertRaises(ValueError): self.verify()

    def test_original_file_only(self):
        self.selection["video_path"] = "COPY.mp4"
        with self.assertRaises(ValueError): self.verify()

    def test_single_final_button(self):
        self.timing["nodes"].append(copy.deepcopy(self.timing["nodes"][-1]))
        with self.assertRaises(ValueError): self.verify()

    def topic_nodes(self, names):
        return [dict(name=n,control_type=50020,parent_id='p',offscreen=False) for n in names]

    def test_bound_empty_topics_ignore_field_labels_but_read_count(self):
        nodes=self.topic_nodes(['标题',':','简介','话题',':','当前话题 ','0',' + 官方活动 ','0'])
        self.assertEqual(read_bound_topics(nodes,'p'),[])

    def test_bound_topics_read_full_chip_names(self):
        self.assertEqual(read_bound_topics(self.topic_nodes(['话题','#','健康','#','健康科普','当前话题 ','2']),'p'),['健康','健康科普'])

    def test_bound_topics_missing_counter_rejected(self):
        with self.assertRaises(ValueError):read_bound_topics(self.topic_nodes(['话题']),'p')

    def test_bound_topics_counter_mismatch_rejected(self):
        with self.assertRaises(ValueError):read_bound_topics(self.topic_nodes(['#','健康','当前话题','0']),'p')


if __name__ == "__main__":
    unittest.main()
