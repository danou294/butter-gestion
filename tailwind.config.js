/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './scripts_manager/templates/**/*.html',
    './templates/**/*.html',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inria Sans', 'system-ui', 'sans-serif'],
        serif: ['Inria Serif', 'Georgia', 'serif'],
      },
    },
  },
  plugins: [],
}
