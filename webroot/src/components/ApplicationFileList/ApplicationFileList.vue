<!--
    ApplicationFileList.vue
    CompactConnect

    Created by InspiringApps on 11/24/2026.
-->

<template>
    <div v-if="files.length" class="application-file-list">
        <div class="file-list-title">{{ $t('application.uploadedDocuments') }}</div>
        <ul class="file-list">
            <li
                v-for="(file, index) in files"
                :key="`${file.filename}-${index}`"
                class="file-item"
            >
                <a
                    v-if="file.downloadUri"
                    :href="file.downloadUri"
                    class="file-name text-link"
                    target="_blank"
                    rel="noopener noreferrer"
                >
                    {{ file.filename }}
                </a>
                <span v-else class="file-name">{{ file.filename }}</span>
                <button
                    v-if="isEditable"
                    type="button"
                    class="text-like remove-file"
                    :aria-label="$t('application.removeDocument', { filename: file.filename })"
                    @click="removeFile(file)"
                >
                    <CloseXIcon />
                </button>
            </li>
        </ul>
    </div>
</template>

<script lang="ts" src="./ApplicationFileList.ts"></script>
<style scoped lang="less" src="./ApplicationFileList.less"></style>
