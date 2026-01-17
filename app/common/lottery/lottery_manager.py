from PySide6.QtCore import QObject, Signal
from loguru import logger
from random import SystemRandom

from app.common.data.list import get_pool_list
from app.common.history import save_lottery_history
from app.common.lottery.lottery_utils import LotteryUtils
from app.common.roll_call.roll_call_utils import RollCallUtils
from app.tools.config import delete_drawn_prize_record_files, record_drawn_prize
from app.tools.settings_access import readme_settings_async

system_random = SystemRandom()


class LotteryManager(QObject):
    """
    抽奖业务逻辑管理器
    负责数据加载、随机抽取、结果处理等非UI逻辑
    """

    # 信号定义
    data_loaded = Signal(bool)
    error_occurred = Signal(str)

    def __init__(self):
        super().__init__()
        self.prizes = []
        self.current_pool_name = ""
        self.current_class_name = ""
        self.current_group_filter = ""
        self.current_gender_filter = ""
        self.current_group_index = 0
        self.current_gender_index = 0
        self.enable_student_assignment = False

    def _format_prize_student_text(self, prize_name, group_name, student_name, mode):
        prize_name = str(prize_name or "")
        group_name = str(group_name or "")
        student_name = str(student_name or "")

        def format_default():
            if group_name and student_name:
                return f"{prize_name}\n{group_name} - {student_name}"
            if group_name:
                return f"{prize_name}\n{group_name}"
            if student_name:
                return f"{prize_name}\n{student_name}"
            return prize_name

        try:
            mode = int(mode)
        except Exception:
            mode = 0

        if mode == 0:
            return format_default()

        mode_spec = {
            1: ("\n", ("prize", "group", "student")),
            2: (" - ", ("prize", "group", "student")),
            3: ("\n", ("prize", "student")),
            4: (" - ", ("prize", "student")),
            5: ("\n", ("prize", "group")),
            6: (" - ", ("prize", "group")),
        }

        spec = mode_spec.get(mode)
        if not spec:
            return format_default()

        sep, order = spec
        value_map = {"prize": prize_name, "group": group_name, "student": student_name}
        parts = [value_map[key] for key in order if value_map.get(key)]
        return sep.join(parts) if parts else prize_name

    def load_data(
        self,
        pool_name,
        class_name=None,
        group_filter=None,
        gender_filter=None,
        group_index=0,
        gender_index=0,
    ):
        """
        加载抽奖池数据（用于动画缓存）
        """
        try:
            self.current_pool_name = pool_name
            self.current_class_name = class_name
            self.current_group_filter = group_filter
            self.current_gender_filter = gender_filter
            self.current_group_index = group_index
            self.current_gender_index = gender_index

            self.enable_student_assignment = bool(
                class_name
                and str(class_name).strip()
                and str(class_name).strip() not in ["不抽取学生", "选择班级"]
            )

            self.prizes = get_pool_list(pool_name)
            self.prizes = [p for p in self.prizes if p.get("exist", True)]
            logger.info(f"加载 {len(self.prizes)} 个奖品在这个奖池中 {pool_name}")

            self.data_loaded.emit(True)
            return True

        except Exception as e:
            logger.exception(f"加载抽奖池数据时出错: {e}")
            self.error_occurred.emit(str(e))
            self.data_loaded.emit(False)
            return False

    def get_random_items(self, count):
        """
        获取随机项（用于动画帧）
        """
        if not self.prizes:
            return []

        # 简单的随机选择用于动画效果
        try:
            # 允许重复用于动画效果
            selected_prizes = [system_random.choice(self.prizes) for _ in range(count)]

            if not self.enable_student_assignment or not self.current_class_name:
                return selected_prizes

            candidates = RollCallUtils._get_filtered_candidates(
                self.current_class_name,
                self.current_group_index,
                self.current_group_filter,
                self.current_gender_index,
                self.current_gender_filter,
            )
            if not candidates:
                return selected_prizes

            show_random = readme_settings_async("lottery_settings", "show_random")
            try:
                show_random = int(show_random or 0)
            except Exception:
                show_random = 0

            from app.common.data.list import get_group_members

            prizes_with_students = []
            for prize in selected_prizes:
                prize_copy = dict(prize)
                prize_name = prize_copy.get("name", "")

                group_name = ""
                student_name = ""
                if self.current_group_index == 1:
                    raw_group = system_random.choice(candidates).get("name", "")
                    include_group = show_random in (0, 1, 2, 5, 6, 7, 8, 9)
                    include_name = show_random in (0, 1, 2, 3, 4, 7, 8, 9, 10, 11)

                    group_name = raw_group if include_group else ""

                    if include_name and raw_group:
                        group_members = get_group_members(
                            self.current_class_name, raw_group
                        )
                        if group_members:
                            selected_member = system_random.choice(group_members)
                            student_name = (selected_member or {}).get("name", "")
                        if not student_name:
                            student_name = raw_group
                else:
                    student_name = system_random.choice(candidates).get("name", "")

                if group_name or student_name:
                    prize_copy["name"] = self._format_prize_student_text(
                        prize_name, group_name, student_name, show_random
                    )

                prizes_with_students.append(prize_copy)

            return prizes_with_students
        except Exception:
            return []

    def draw_final_items(self, count):
        """
        执行最终抽取
        """
        result = LotteryUtils.draw_random_prizes(self.current_pool_name, count)
        if not isinstance(result, dict):
            return {
                "selected_prizes": [],
                "pool_name": self.current_pool_name,
                "selected_prizes_dict": [],
            }

        if result.get("reset_required"):
            return result

        if not self.enable_student_assignment or not self.current_class_name:
            return result

        selected_prizes_dict = result.get("selected_prizes_dict") or []
        prize_names = [
            p.get("name", "") for p in selected_prizes_dict if isinstance(p, dict)
        ]
        draw_count = len(prize_names)
        if draw_count <= 0:
            return result

        threshold = LotteryUtils._get_prize_draw_threshold()
        if threshold is None:
            half_repeat = 0
        else:
            try:
                half_repeat = int(threshold)
            except Exception:
                half_repeat = 1
        students_result = LotteryUtils.draw_random_students(
            self.current_class_name,
            self.current_group_index,
            self.current_group_filter,
            self.current_gender_index,
            self.current_gender_filter,
            draw_count,
            half_repeat,
            pool_name=self.current_pool_name,
            prize_list=prize_names,
        )

        if isinstance(students_result, dict) and students_result.get("reset_required"):
            return {
                "reset_required": True,
                "reset_scope": "students",
                "pool_name": self.current_pool_name,
                "class_name": self.current_class_name,
                "group_filter": self.current_group_filter,
                "gender_filter": self.current_gender_filter,
            }

        selected_students = (students_result or {}).get("selected_students") or []
        selected_students_dict = (students_result or {}).get(
            "selected_students_dict"
        ) or []

        selected_prizes_with_students = []
        updated_prizes_dict = []
        show_random = readme_settings_async("lottery_settings", "show_random")
        try:
            show_random = int(show_random or 0)
        except Exception:
            show_random = 0

        from app.common.data.list import get_group_members

        for idx, prize in enumerate(selected_prizes_dict):
            if not isinstance(prize, dict):
                continue

            prize_id = prize.get("id", "")
            prize_name = prize.get("name", "")
            prize_exist = prize.get("exist", True)

            student_tuple = (
                selected_students[idx] if idx < len(selected_students) else None
            )
            student_dict = (
                selected_students_dict[idx]
                if idx < len(selected_students_dict)
                else None
            )

            display_name = prize_name
            if student_tuple and len(student_tuple) >= 2 and student_tuple[1]:
                group_name = ""
                student_name = ""

                if self.current_group_index == 1:
                    raw_group = str(student_tuple[1])
                    include_group = show_random in (0, 1, 2, 5, 6, 7, 8, 9)
                    include_name = show_random in (0, 1, 2, 3, 4, 7, 8, 9, 10, 11)

                    group_name = raw_group if include_group else ""

                    if include_name and raw_group:
                        group_members = get_group_members(
                            self.current_class_name, raw_group
                        )
                        if group_members:
                            selected_member = system_random.choice(group_members)
                            student_name = (selected_member or {}).get("name", "")
                        if not student_name:
                            student_name = raw_group
                else:
                    student_name = str(student_tuple[1])

                display_name = self._format_prize_student_text(
                    prize_name, group_name, student_name, show_random
                )

            selected_prizes_with_students.append((prize_id, display_name, prize_exist))

            prize_copy = dict(prize)
            if isinstance(student_dict, dict):
                prize_copy["student"] = student_dict
                prize_copy["student_id"] = student_dict.get("id", "")
                prize_copy["student_name"] = student_dict.get("name", "")
                prize_copy["student_exist"] = student_dict.get("exist", True)
            updated_prizes_dict.append(prize_copy)

        result["selected_prizes"] = selected_prizes_with_students
        result["selected_prizes_dict"] = updated_prizes_dict
        result["selected_students_dict"] = selected_students_dict
        return result

    def save_result(
        self, selected_items, group_filter="", gender_filter="", save_temp=False
    ):
        """
        保存抽奖结果

        Args:
            selected_items: 选中的奖品/学生列表 (dict列表)
            group_filter: 班级/小组过滤器
            gender_filter: 性别过滤器
            save_temp: 是否保存临时记录 (用于不重复/半重复模式)
        """
        if save_temp:
            prize_names = [
                item.get("name", "")
                for item in (selected_items or [])
                if isinstance(item, dict)
            ]
            record_drawn_prize(self.current_pool_name, prize_names)

        save_lottery_history(
            self.current_pool_name, selected_items, group_filter, gender_filter
        )

        if self.enable_student_assignment and self.current_class_name:
            student_dicts = []
            for item in selected_items or []:
                if not isinstance(item, dict):
                    continue
                student = item.get("student")
                if isinstance(student, dict):
                    student_dicts.append(student)

            selected_names = [
                s.get("name", "") for s in student_dicts if isinstance(s, dict)
            ]
            threshold = LotteryUtils._get_prize_draw_threshold()
            if save_temp and threshold is not None:
                try:
                    half_repeat = int(threshold)
                except Exception:
                    half_repeat = 1
            else:
                half_repeat = 0
            RollCallUtils.record_drawn_students(
                self.current_class_name,
                selected_names,
                student_dicts,
                self.current_gender_filter,
                self.current_group_filter,
                half_repeat,
            )

    def reset_records(self, parent=None):
        """重置抽取记录"""
        delete_drawn_prize_record_files(self.current_pool_name)
        if self.enable_student_assignment and self.current_class_name:
            RollCallUtils.reset_drawn_records(
                parent,
                self.current_class_name,
                self.current_gender_filter,
                self.current_group_filter,
            )
