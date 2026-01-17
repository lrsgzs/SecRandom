from PySide6.QtCore import QObject, Signal
from loguru import logger
from random import SystemRandom

from app.common.data.list import get_student_list, filter_students_data
from app.common.history import calculate_weight
from app.common.roll_call.roll_call_utils import RollCallUtils
from app.tools.config import remove_record

system_random = SystemRandom()


class RollCallManager(QObject):
    """
    点名业务逻辑管理器
    负责数据加载、随机抽取、结果处理等非UI逻辑
    """

    # 信号定义
    data_loaded = Signal(bool)  # 数据加载完成信号
    error_occurred = Signal(str)  # 错误信号

    def __init__(self):
        super().__init__()
        self.students = []
        self.weights = []
        self.current_class_name = ""
        self.current_group_filter = ""
        self.current_gender_filter = ""
        self.current_group_index = 0
        self.current_gender_index = 0
        self.half_repeat = 0

    def load_data(
        self,
        class_name,
        group_filter,
        gender_filter,
        group_index,
        gender_index,
        half_repeat,
    ):
        """
        加载学生数据
        """
        try:
            self.current_class_name = class_name
            self.current_group_filter = group_filter
            self.current_gender_filter = gender_filter
            self.current_group_index = group_index
            self.current_gender_index = gender_index
            self.half_repeat = half_repeat

            # 获取原始学生列表
            raw_students = get_student_list(class_name)

            # 过滤数据
            self.students = filter_students_data(
                raw_students, group_index, group_filter, gender_index, gender_filter
            )

            # 计算权重
            self.weights = self._calculate_weights()

            logger.info(f"加载 {len(self.students)} 个学生在这个班级 {class_name}")
            self.data_loaded.emit(True)
            return True

        except Exception as e:
            logger.exception(f"加载学生数据时出错: {e}")
            self.error_occurred.emit(str(e))
            self.data_loaded.emit(False)
            return False

    def _calculate_weights(self):
        """计算权重"""
        # 转换 self.students (tuples) 为 dict list 以适配 calculate_weight
        students_dicts = []
        for s in self.students:
            students_dicts.append(
                {"id": s[0], "name": s[1], "gender": s[2], "group": s[3], "exist": s[4]}
            )

        # 批量计算权重
        weighted_students = calculate_weight(students_dicts, self.current_class_name)

        # 提取权重值，保持顺序一致
        weights = []
        for s in weighted_students:
            weights.append(s.get("next_weight", 1.0))

        return weights

    def get_random_students(self, count):
        """
        获取随机学生列表（用于动画帧）
        """
        if not self.students:
            return []

        # 如果需要抽取的数量大于学生总数，允许重复
        allow_repeat = count > len(self.students)

        selected = []
        if allow_repeat:
            # 简单的随机选择用于动画效果
            selected = [system_random.choice(self.students) for _ in range(count)]
        else:
            # 简单的随机选择用于动画效果（无权重）
            # 注意：权重采样(without replacement)比较复杂且对动画效果影响不大，
            # 这里直接使用均匀分布采样以保证性能和避免重复
            selected = system_random.sample(self.students, k=count)

        return selected

    def draw_final_students(self, count):
        """
        执行最终抽取
        """
        # 使用RollCallUtils中的核心抽取逻辑，它处理了去重、权重等复杂逻辑
        result = RollCallUtils.draw_random_students(
            self.current_class_name,
            self.current_group_index,
            self.current_group_filter,
            self.current_gender_index,
            self.current_gender_filter,
            count,
            self.half_repeat,
        )
        return result

    def save_result(self, selected_students, selected_students_dict):
        """
        保存抽取结果
        """
        return RollCallUtils.record_drawn_students(
            self.current_class_name,
            selected_students,
            selected_students_dict,
            self.current_gender_filter,
            self.current_group_filter,
            self.half_repeat,
        )

    def reset_records(self):
        """重置抽取记录"""
        remove_record(
            self.current_class_name,
            self.current_gender_filter,
            self.current_group_filter,
        )
