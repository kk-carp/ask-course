import { createApp } from "vue";
import "ant-design-vue/dist/reset.css";
import AdminApp from "./AdminApp.vue";
import "./admin.css";
const answerStyles = document.createElement("style");
answerStyles.textContent = window.AnswerFormat.styles;
document.head.append(answerStyles);
createApp(AdminApp).mount("#admin-app");
