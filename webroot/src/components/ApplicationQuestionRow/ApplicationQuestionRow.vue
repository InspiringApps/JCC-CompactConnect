<!--
    ApplicationQuestionRow.vue
    CompactConnect

    Created by InspiringApps on 11/24/2026.
-->

<template>
    <li class="question-row" :class="{ 'is-stacked': isStacked }">
        <div :id="formInput.name" class="question-text">
            {{ formInput.label }}<span v-if="isRequired" class="required-indicator">*</span>
        </div>
        <InputRadioGroup
            :formInput="formInput"
            :isGroupHorizontal="true"
            class="question-input"
        />
    </li>
</template>

<script lang="ts" src="./ApplicationQuestionRow.ts"></script>
<style scoped lang="less" src="./ApplicationQuestionRow.less"></style>
