import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'
import { setupPermissionDirective } from './directives/permission'
import './styles/index.css'

const app = createApp(App)
app.use(createPinia())
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}
app.use(ElementPlus)
setupPermissionDirective(app)
app.use(router)
app.mount('#app')
