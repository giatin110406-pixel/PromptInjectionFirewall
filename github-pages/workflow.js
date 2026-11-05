document.querySelectorAll('.flow-canvas a[href^="#step-"]').forEach((link) => {
  link.addEventListener('click', () => {
    const target = document.getElementById(link.hash.slice(1));
    if (target) target.open = true;
  });
});
