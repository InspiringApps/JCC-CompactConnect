<!--
    ConductHistory.vue
    CompactConnect

    Created by InspiringApps on 11/24/2026.
-->

<template>
    <ApplicationSectionLayout
        class="conduct-history-container"
        :title="sectionTitle"
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
        <div :key="formRenderKey" class="conduct-history-content">
            <section class="section-card questions-card">
                <div
                    v-for="group in attestationGroups"
                    :key="group.key"
                    class="card-group attestation-group"
                    :class="`group-${group.key}`"
                >
                    <h2 class="card-title">{{ group.title }}</h2>
                    <ul class="question-list">
                        <template v-for="attestation in group.attestations" :key="attestation.attestationId">
                            <ApplicationQuestionRow :formInput="formData[getAttestationKey(attestation)]" />
                            <li
                                v-if="attestation.attestationId === convictionAttestationId && isConvicted"
                                class="sub-panel conviction-panel"
                            >
                                <div
                                    v-for="(entry, index) in convictionEntries"
                                    :key="entry.id"
                                    class="conviction-entry"
                                >
                                    <div class="conviction-header">
                                        <h3 class="card-subtitle">
                                            {{ $t('application.convictionDetailsTitle') }}
                                            <span v-if="convictionEntries.length > 1">({{ index + 1 }})</span>
                                        </h3>
                                        <button
                                            v-if="convictionEntries.length > 1"
                                            type="button"
                                            class="text-like remove-conviction"
                                            @click="removeConviction(entry)"
                                        >
                                            {{ $t('application.removeConviction') }}
                                        </button>
                                    </div>
                                    <div class="form-grid">
                                        <InputText :formInput="convictionInput(entry, 'Charge')" />
                                        <InputText :formInput="convictionInput(entry, 'Location')" />
                                        <InputDate
                                            :formInput="convictionInput(entry, 'Date')"
                                            :yearRange="[1950, new Date().getFullYear()]"
                                            :maxDate="new Date()"
                                            :preventMinMaxNavigation="true"
                                            :textInput="{ format: 'MM/dd/yyyy', openMenu: false }"
                                        />
                                        <InputText :formInput="convictionInput(entry, 'Type')" />
                                    </div>
                                </div>
                                <button type="button" class="text-like add-conviction" @click="addConviction">
                                    + {{ $t('application.addConviction') }}
                                </button>
                            </li>
                        </template>
                    </ul>
                </div>
                <InputCheckbox
                    v-if="confirmationAttestation"
                    :formInput="formData[getAttestationKey(confirmationAttestation)]"
                    class="attestation-checkbox confirmation-checkbox"
                />
            </section>
            <section class="section-card documents-card" aria-labelledby="supporting-documents-heading">
                <h2 id="supporting-documents-heading" class="card-title">
                    {{ $t('application.supportingDocumentsTitle') }}
                </h2>
                <p class="card-intro">{{ $t('application.supportingDocumentsIntro') }}</p>
                <ApplicationFileList
                    v-if="existingDocuments.length"
                    :files="existingDocuments"
                    :isEditable="isEditable"
                    class="existing-files"
                    @remove="removeExistingDocument"
                />
                <InputFile :formInput="formData.documents" class="file-input" />
                <InputTextarea
                    :formInput="formData.notes"
                    :shouldResizeY="true"
                    class="explanation-input"
                />
            </section>
        </div>
    </ApplicationSectionLayout>
</template>

<script lang="ts" src="./ConductHistory.ts"></script>
<style scoped lang="less" src="./ConductHistory.less"></style>
