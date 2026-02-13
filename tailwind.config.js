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
  plugins: [require('daisyui')],
  daisyui: {
    themes: [
      {
        butter: {
          'primary': '#60BC81',          // Vert Butter
          'primary-content': '#FFFFFF',
          'secondary': '#535353',         // Gris texte
          'secondary-content': '#FFFFFF',
          'accent': '#C9C1B1',           // Beige foncé
          'accent-content': '#111111',
          'neutral': '#111111',          // Noir texte
          'neutral-content': '#FFFFFF',
          'base-100': '#FFFFFF',         // Fond cartes
          'base-200': '#F1EFEB',         // Fond page (beige)
          'base-300': '#C9C1B1',         // Bordures
          'base-content': '#111111',
          'info': '#535353',
          'success': '#60BC81',          // Vert
          'success-content': '#FFFFFF',
          'warning': '#FFC107',          // Jaune (DEV env)
          'error': '#D3695E',            // Rouge Butter
          'error-content': '#FFFFFF',
          '--rounded-box': '14px',
          '--rounded-btn': '14px',
          '--rounded-badge': '14px',
        },
      },
    ],
    darkTheme: false,
    logs: false,
  },
}
