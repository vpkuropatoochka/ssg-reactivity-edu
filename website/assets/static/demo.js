const taskList = document.querySelector("#task-list");
const tasks = [...taskList.querySelectorAll("input")];
const progress = document.querySelector("#task-progress");

function updateProgress() {
  const completed = tasks.filter(task => task.checked).length;
  const percent = Math.round(100 * completed / tasks.length);
  progress.textContent = `Выполнено ${completed} из ${tasks.length} (${percent} %)`;
}

taskList.disabled = false;
taskList.addEventListener("change", updateProgress);
window.addEventListener("pageshow", updateProgress);
updateProgress();
