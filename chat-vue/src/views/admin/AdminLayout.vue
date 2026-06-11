<template>
  <div class="min-h-screen bg-gray-50">
    <nav class="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-4">
      <span class="font-semibold text-gray-800">Admin</span>
      <RouterLink to="/admin/dashboard" class="text-sm text-gray-600 hover:text-gray-900">Dashboard</RouterLink>
      <RouterLink to="/admin/users" class="text-sm text-gray-600 hover:text-gray-900">Users</RouterLink>
      <RouterLink to="/" class="ml-auto text-sm text-gray-500 hover:text-gray-700">← Back to app</RouterLink>
    </nav>
    <main class="p-6">
      <RouterView />
    </main>
  </div>
</template>
