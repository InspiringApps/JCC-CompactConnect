<!--
    ApplicationSectionLayout.vue
    CompactConnect

    Created by InspiringApps on 11/24/2026.
-->

<template>
    <div class="application-section-container">
        <div class="section-content section-header">
            <router-link v-if="hasChecklistRoute" class="back-link" :to="checklistRoute">
                {{ $t('application.backToChecklist') }}
            </router-link>
            <h1 class="section-title">{{ title }}</h1>
            <p v-if="intro" class="section-intro">{{ intro }}</p>
            <div v-if="isLoadError" class="section-load-error" role="alert">
                <p class="load-error-message">{{ $t('application.sectionLoadError') }}</p>
                <router-link v-if="hasChecklistRoute" class="text-link" :to="checklistRoute">
                    {{ $t('application.backToChecklist') }}
                </router-link>
            </div>
            <template v-else-if="isFormReady">
                <div v-if="isNeedsAttention" class="attention-banner" role="alert">
                    <div class="attention-title">
                        <AlertTriangleIcon class="attention-icon" />
                        {{ $t('application.issueWithApplication') }}
                    </div>
                    <p
                        v-for="(note, index) in attentionNotes"
                        :key="index"
                        class="attention-note"
                    >
                        {{ note }}
                    </p>
                </div>
                <div v-if="!isEditable" class="not-editable-message" role="status">
                    {{ $t('application.sectionNotEditable') }}
                </div>
            </template>
        </div>
        <form
            v-if="isFormReady && !isLoadError"
            class="section-form"
            novalidate
            @submit.prevent="submit"
        >
            <div class="section-content section-body">
                <div v-if="isMockPopulateEnabled" class="mock-actions">
                    <MockPopulate :isEnabled="isMockPopulateEnabled" @selected="mockPopulate" />
                    <button type="button" class="text-like clear-form" @click="clearForm">
                        {{ $t('common.clear') }}
                    </button>
                </div>
                <slot></slot>
            </div>
            <div class="section-footer">
                <div class="section-content section-footer-content">
                    <InputSubmit
                        :formInput="submitFormInput"
                        :label="saveLabel || $t('common.save')"
                        :isEnabled="isSaveEnabled"
                        class="save-button"
                    />
                    <InputButton
                        v-if="isSaveSuccessful"
                        :label="$t('common.continue')"
                        :isTransparent="true"
                        :shouldHideMargin="true"
                        class="continue-button"
                        @click="continueToNext"
                    />
                </div>
            </div>
        </form>
        <slot name="after-form"></slot>
    </div>
</template>

<script lang="ts" src="./ApplicationSectionLayout.ts"></script>
<style scoped lang="less" src="./ApplicationSectionLayout.less"></style>
