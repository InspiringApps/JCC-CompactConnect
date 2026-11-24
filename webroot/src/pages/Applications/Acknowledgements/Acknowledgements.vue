<!--
    Acknowledgements.vue
    CompactConnect

    Created by InspiringApps on 11/24/2026.
-->

<template>
    <ApplicationSectionLayout
        class="acknowledgements-container"
        :title="sectionTitle"
        :intro="$t('application.acknowledgementsIntro')"
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
        <div :key="formRenderKey" class="acknowledgements-content">
            <section class="section-card statements-card" aria-labelledby="statements-heading">
                <h2 id="statements-heading" class="visually-hidden">{{ sectionTitle }}</h2>
                <div class="statements-header" aria-hidden="true">
                    <span>{{ $t('application.statementHeader') }}</span>
                    <span>{{ $t('application.responseHeader') }}</span>
                </div>
                <ul class="question-list statements-list">
                    <ApplicationQuestionRow
                        v-for="attestation in statementAttestations"
                        :key="attestation.attestationId"
                        :formInput="formData[getAttestationKey(attestation)]"
                    />
                </ul>
            </section>
            <section class="section-card sign-card" aria-labelledby="sign-and-submit-heading">
                <h2 id="sign-and-submit-heading" class="card-title">{{ $t('application.signAndSubmitTitle') }}</h2>
                <div v-if="signAndSubmitAttestation" class="sign-and-submit-text">
                    {{ signAndSubmitAttestation.text }}
                </div>
                <InputCheckbox
                    v-if="factualAttestation"
                    :formInput="formData[getAttestationKey(factualAttestation)]"
                    class="attestation-checkbox factual-checkbox"
                />
                <div class="form-grid">
                    <InputText :formInput="formData.signatureName" />
                </div>
            </section>
        </div>
    </ApplicationSectionLayout>
</template>

<script lang="ts" src="./Acknowledgements.ts"></script>
<style scoped lang="less" src="./Acknowledgements.less"></style>
