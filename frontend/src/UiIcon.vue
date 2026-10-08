<script setup>
defineProps({name: String});
const paths = {
  history: 'M3 11a9 9 0 1 1 2.7 6.4M3 4v7h7M12 7v5l3 2',
  new: 'M12 3v18M3 12h18',
  collapse: 'm5 9 7 7 7-7',
  send: 'M12 19V5m-6 6 6-6 6 6',
  more: 'M5 12h.01M12 12h.01M19 12h.01',
  search: 'M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  edit: 'm16 3 5 5-12 12-6 1 1-6L16 3Zm-3 3 5 5',
  delete: 'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7',
};
</script>
<template><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path :d="paths[name]" /></svg></template>
