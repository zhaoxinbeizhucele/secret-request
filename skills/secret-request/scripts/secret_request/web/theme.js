'use strict';
// Theme preference shared by the homepage and the input page.
// Loaded synchronously in <head> (CSP allows same-origin scripts only), so the stored
// theme is applied to <html data-theme> before first paint. "system" removes the
// attribute and the CSS prefers-color-scheme rule applies, including live OS changes.
(function () {
  var KEY = 'secret-request-theme';
  var CHOICES = ['light', 'dark', 'system'];
  var root = document.documentElement;

  function read() {
    try {
      var value = window.localStorage.getItem(KEY);
      return value === 'light' || value === 'dark' ? value : 'system';
    } catch (e) {
      return 'system';
    }
  }
  function store(value) {
    try {
      if (value === 'system') window.localStorage.removeItem(KEY);
      else window.localStorage.setItem(KEY, value);
    } catch (e) { /* Storage unavailable: the choice lasts for this page only. */ }
  }
  function apply(value) {
    if (value === 'light' || value === 'dark') root.setAttribute('data-theme', value);
    else root.removeAttribute('data-theme');
  }

  var current = read();
  apply(current);
  root.classList.add('theme-js');

  function sync() {
    var options = document.querySelectorAll('[data-theme-choice]');
    for (var i = 0; i < options.length; i++) {
      var on = options[i].getAttribute('data-theme-choice') === current;
      options[i].setAttribute('aria-checked', String(on));
      options[i].tabIndex = on ? 0 : -1;
    }
  }
  function choose(value, focus) {
    current = CHOICES.indexOf(value) < 0 ? 'system' : value;
    apply(current); store(current); sync();
    if (focus) {
      var target = document.querySelector('[data-theme-choice="' + current + '"]');
      if (target) target.focus();
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    var groups = document.querySelectorAll('.theme-switch');
    for (var g = 0; g < groups.length; g++) {
      groups[g].addEventListener('click', function (event) {
        var option = event.target.closest('[data-theme-choice]');
        if (option) choose(option.getAttribute('data-theme-choice'), false);
      });
      groups[g].addEventListener('keydown', function (event) {
        var step = {ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1}[event.key];
        var index = CHOICES.indexOf(current);
        if (step) index = (index + step + CHOICES.length) % CHOICES.length;
        else if (event.key === 'Home') index = 0;
        else if (event.key === 'End') index = CHOICES.length - 1;
        else return;
        event.preventDefault();
        choose(CHOICES[index], true);
      });
    }
    sync();
  });

  // Keep other open tabs in step with a change made elsewhere.
  window.addEventListener('storage', function (event) {
    if (event.key === KEY || event.key === null) { current = read(); apply(current); sync(); }
  });
})();
