const form = document.querySelector('form');
form.addEventListener('submit', (event) => {
  event.preventDefault();
  const status = form.querySelector('output');
  status.textContent = form.dataset.successMessage;
  status.dataset.formAgentSubmitted = 'true';
  status.hidden = false;
});
