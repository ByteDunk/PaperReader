import { defineAsyncComponent } from 'vue'
import PaperListPanel from '../panels/PaperListPanel.vue'
import OriginalViewPanel from '../panels/OriginalViewPanel.vue'
import ReflowViewPanel from '../panels/ReflowViewPanel.vue'
import ToolboxPanel from '../panels/ToolboxPanel.vue'
import TranslationPanel from '../panels/TranslationPanel.vue'
import AiAssistantPanel from '../panels/AiAssistantPanel.vue'

export const panels = {
  'paper-list': { title: '论文列表', icon: 'library', component: PaperListPanel },
  original: { title: '论文原文', icon: 'file-text', component: OriginalViewPanel },
  reflow: { title: '论文重排', icon: 'article', component: ReflowViewPanel },
  toolbox: { title: '工具', icon: 'sliders', component: ToolboxPanel },
  translation: { title: '对照翻译', icon: 'languages', component: TranslationPanel },
  assistant: { title: 'AI 助手', icon: 'sparkles', component: AiAssistantPanel },
  tutorial: { title: '使用教程', icon: 'book-open', component: defineAsyncComponent(() => import('../tutorial/TutorialPanel.vue')) },
}
