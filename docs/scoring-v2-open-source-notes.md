# 评分体系 v2 的开源方案参考

本项目只借鉴评价原则和交互模型，没有复制下列 GPL/AGPL 项目的实现代码。

## Moodle

- Quiz 统计把观察成绩与测量误差、标准误和题目区分度分开；
- 统计分析可只采用首次尝试，避免重复练习破坏独立性假设；
- Quiz 支持最高、平均、首次、末次等多次尝试汇总策略。

参考：

- https://docs.moodle.org/en/Quiz_statistics_report
- https://docs.moodle.org/dev/Quiz_statistics_calculations
- https://github.com/moodle/moodle/blob/main/public/mod/quiz/lib.php

知链对应实现：观察表现、能力暂估、置信度与正式评级分离；相同题目重复尝试不重复抬高能力。

## Open edX

- Homework、Lab、Midterm、Final 等评分类型分别配置权重；
- 每题可设置最大尝试次数，并区分首次、最后、最高、平均成绩策略。

参考：

- https://docs.openedx.org/en/latest/educators/references/grading/gradebook_assignment_types.html
- https://github.com/openedx/openedx-platform/blob/master/xmodule/capa_block.py

知链对应实现：知识子分与实操子分分离，纸面 Quiz 不替代岗位实操。

## TAO

- 主观题可按多个 trait/评分维度分别给分；
- 不确定的评分可标记并进入人工复核流程。

参考：

- https://userguide.taotesting.com/user-documentation/latest/public/scoring-test-takers-responses
- https://userguide.taotesting.com/knowledge-base/latest/public/how-to-manually-score-a-test

知链对应实现：主观题保留带权评分点、语义与事实分、安全红线和评分器置信度；低置信结果进入待复核。
