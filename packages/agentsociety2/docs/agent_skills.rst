Agent Skills（智能体技能）
==========================

Agent Skills 为仿真参与者组织行为能力。模型先查看技能的名称与描述，再按需激活正文、读取参考资料或执行脚本。目录可见、已激活和已执行是三个不同阶段。

当前内置技能是 :ref:`daily-guidance`，用于小时及以下时间尺度的日常行为。自定义技能放在研究工作区的 ``custom/skills/``；从零开始编写时先读 :doc:`/skill_guide`。研究助手用于文献、假设和实验的技能见 :doc:`/skills`。

.. grid:: 1 1 3 3
   :gutter: 3
   :class-container: topic-links

   .. grid-item-card:: 技能发现、激活与内置技能
      :link: agent_skills/usage
      :link-type: doc
      :class-card: doc-card

      区分发现、激活与执行，了解目录格式和内置 daily-guidance。

   .. grid-item-card:: 技能脚本与生命周期
      :link: agent_skills/execution
      :link-type: doc
      :class-card: doc-card

      理解脚本上下文、执行隔离、并发约束与生命周期 hook。

   .. grid-item-card:: 技能扩展与调试
      :link: agent_skills/authoring
      :link-type: doc
      :class-card: doc-card

      参考脚本示例、注册表接口和检查清单，扩展智能体行为。

.. toctree::
   :hidden:
   :maxdepth: 1

   agent_skills/usage
   agent_skills/execution
   agent_skills/authoring

.. raw:: html

   <div class="guide-redirects" hidden>
   <span id="id2"></span><a data-legacy-fragment="id2" href="agent_skills/usage.html#agent-skills-usage-3">Moved section</a>
   <span id="skill"></span><a data-legacy-fragment="skill" href="agent_skills/usage.html#agent-skills-usage-2">Moved section</a>
   <span id="skill-md"></span><a data-legacy-fragment="skill-md" href="agent_skills/usage.html#agent-skills-usage-1">Moved section</a>
   <span id="id3"></span><a data-legacy-fragment="id3" href="agent_skills/usage.html#agent-skills-usage-0">Moved section</a>
   <span id="id4"></span><a data-legacy-fragment="id4" href="agent_skills/execution.html#agent-skills-execution-9">Moved section</a>
   <span id="entrypoint-skill"></span><a data-legacy-fragment="entrypoint-skill" href="agent_skills/execution.html#agent-skills-execution-8">Moved section</a>
   <span id="skillscriptcontext"></span><a data-legacy-fragment="skillscriptcontext" href="agent_skills/execution.html#agent-skills-execution-7">Moved section</a>
   <span id="id5"></span><a data-legacy-fragment="id5" href="agent_skills/execution.html#agent-skills-execution-6">Moved section</a>
   <span id="hook"></span><a data-legacy-fragment="hook" href="agent_skills/execution.html#agent-skills-execution-5">Moved section</a>
   <span id="daily-guidance"></span><a data-legacy-fragment="daily-guidance" href="agent_skills/usage.html#agent-skills-usage-4">Moved section</a>
   <span id="hook-pre-step-post-step"></span><a data-legacy-fragment="hook-pre-step-post-step" href="agent_skills/execution.html#agent-skills-execution-10">Moved section</a>
   <span id="skill-env"></span><a data-legacy-fragment="skill-env" href="agent_skills/authoring.html#agent-skills-authoring-15">Moved section</a>
   <span id="skillregistry-api"></span><a data-legacy-fragment="skillregistry-api" href="agent_skills/authoring.html#agent-skills-authoring-14">Moved section</a>
   <span id="id7"></span><a data-legacy-fragment="id7" href="agent_skills/authoring.html#agent-skills-authoring-13">Moved section</a>
   <span id="id8"></span><a data-legacy-fragment="id8" href="agent_skills/authoring.html#agent-skills-authoring-12">Moved section</a>
   <span id="id9"></span><a data-legacy-fragment="id9" href="agent_skills/authoring.html#agent-skills-authoring-11">Moved section</a>
   <span id="id1"></span>
   </div>
