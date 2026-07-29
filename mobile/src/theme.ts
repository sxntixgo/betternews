/** One palette, so a colour is changed in one place rather than nine. */
export const colors = {
  bg: '#ffffff',
  surface: '#f5f6f8',
  border: '#e3e6ea',
  text: '#16181d',
  muted: '#6b7280',
  accent: '#1d6fe0',
  accentSoft: '#e9f1fd',
  danger: '#b3261e',
  dangerSoft: '#fdecea',
  active: '#0f7b3d',
} as const;

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 } as const;

export const radius = { sm: 4, md: 8, pill: 999 } as const;

export const font = {
  title: 17,
  body: 15,
  small: 13,
  tiny: 11,
} as const;
