<!--
    HomeState.vue
    CompactConnect

    Created by InspiringApps on 11/24/2026.
-->

<template>
    <ApplicationSectionLayout
        class="home-state-container"
        :title="sectionTitle"
        :intro="$t('application.homeStateIntro')"
        :compactType="compactType"
        :applicationId="applicationId"
        :isLoadError="isLoadError"
        :isFormReady="isFormReady"
        :isEditable="isEditable"
        :isNeedsAttention="isNeedsAttention"
        :attentionNotes="attentionNotes"
        :submitFormInput="formData.submit"
        :saveLabel="saveLabel"
        :isSaveEnabled="isSaveEnabled"
        :isSaveSuccessful="isFormSuccessful"
        :isMockPopulateEnabled="isMockPopulateEnabled"
        @submit="handleSubmit"
        @continue="continueToNextSection"
        @mock-populate="handleMockPopulate"
        @clear="handleClearForm"
    >
        <div :key="formRenderKey" class="home-state-content">
            <section
                v-for="section in homeStateSections"
                :key="section.type"
                class="section-card home-state-section"
                :class="`home-state-${section.type}`"
                :aria-labelledby="`${section.type}-home-state-heading`"
            >
                <h2 :id="`${section.type}-home-state-heading`" class="card-title">
                    {{ $t('application.homeStateLabel', { type: section.typeName }) }}
                </h2>
                <div class="form-grid">
                    <InputSelect :formInput="formInputFor(section.type, 'State')" />
                    <InputDate
                        :formInput="formInputFor(section.type, 'StartDate')"
                        :yearRange="[1950, new Date().getFullYear() + 1]"
                        :preventMinMaxNavigation="true"
                        :textInput="{ format: 'MM/dd/yyyy', openMenu: false }"
                    />
                </div>
                <div class="military-container">
                    <InputCheckbox
                        :formInput="formInputFor(section.type, 'IsActiveMilitary')"
                        class="attestation-checkbox military-checkbox"
                        @checked="onActiveMilitaryChange(section.type)"
                        @unchecked="onActiveMilitaryChange(section.type)"
                    />
                    <p class="military-subtext">{{ $t('application.isActiveMilitarySubtext') }}</p>
                </div>
                <div v-if="isActiveMilitary(section.type)" class="sub-panel military-documents">
                    <h3 class="card-subtitle">
                        {{ $t('application.militaryDocumentsTitle') }}<span class="required-indicator">*</span>
                    </h3>
                    <p class="card-intro">{{ $t('application.militaryDocumentsIntro') }}</p>
                    <ApplicationFileList
                        v-if="(existingDocuments[section.type] || []).length"
                        :files="existingDocuments[section.type]"
                        :isEditable="isEditable"
                        class="existing-files"
                        @remove="(file) => removeExistingDocument(section.type, file)"
                    />
                    <InputFile :formInput="formInputFor(section.type, 'MilitaryDocuments')" class="file-input" />
                </div>
                <div
                    v-for="formInput in attestationInputs(section)"
                    :key="formInput.id"
                    class="home-state-attestation"
                >
                    <InputCheckbox :formInput="formInput" class="attestation-checkbox" />
                    <a
                        class="text-link policy-link"
                        :href="homeStatePolicyUrl"
                        target="_blank"
                        rel="noopener noreferrer"
                    >
                        {{ $t('application.readFullPolicy') }}
                        <span class="visually-hidden">{{ $t('common.opensInNewTab') }}</span>
                    </a>
                </div>
            </section>
        </div>
    </ApplicationSectionLayout>
</template>

<script lang="ts" src="./HomeState.ts"></script>
<style scoped lang="less" src="./HomeState.less"></style>
