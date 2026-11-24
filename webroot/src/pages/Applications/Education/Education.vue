<!--
    Education.vue
    CompactConnect

    Created by InspiringApps on 11/24/2026.
-->

<template>
    <ApplicationSectionLayout
        class="education-container"
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
        <div :key="formRenderKey" class="education-content">
            <section class="section-card" aria-labelledby="degree-heading">
                <h2 id="degree-heading" class="card-title">{{ $t('application.degreeInformationTitle') }}</h2>
                <div class="form-grid">
                    <InputText :formInput="formData.nameAtTime" />
                    <InputText :formInput="formData.institution" />
                    <InputText :formInput="formData.city" />
                    <InputText :formInput="formData.state" />
                    <div>
                        <InputSelect :formInput="formData.degreeType" />
                        <p class="input-hint">{{ $t('application.degreeHint') }}</p>
                    </div>
                    <InputText :formInput="formData.program" />
                    <InputText :formInput="formData.department" />
                    <InputDate
                        :formInput="formData.conferredDate"
                        :yearRange="[1950, new Date().getFullYear()]"
                        :maxDate="new Date()"
                        :preventMinMaxNavigation="true"
                        :textInput="{ format: 'MM/dd/yyyy', openMenu: false }"
                    />
                </div>
                <ul class="question-list">
                    <ApplicationQuestionRow :formInput="formData.isCompleted" :isStacked="true" />
                </ul>
            </section>
            <section class="section-card" aria-labelledby="accreditation-heading">
                <h2 id="accreditation-heading" class="card-title">{{ $t('application.accreditationTitle') }}</h2>
                <div class="info-box">
                    <InfoCircleIcon class="info-icon" aria-hidden="true" />
                    <p class="info-text">
                        {{ $t('application.accreditationInfoStart') }}
                        <a
                            class="text-link"
                            :href="accreditedProgramsSearchUrl"
                            target="_blank"
                            rel="noopener noreferrer"
                        >{{ $t('application.searchAccreditedPrograms') }}<span class="visually-hidden">
                            {{ $t('common.opensInNewTab') }}</span></a>{{ $t('application.accreditationInfoMiddle') }}
                        <a
                            class="text-link"
                            :href="historicalVerificationUrl"
                            target="_blank"
                            rel="noopener noreferrer"
                        >{{ $t('application.requestHistoricalVerification') }}<span class="visually-hidden">
                            {{ $t('common.opensInNewTab') }}</span></a>
                        {{ $t('application.accreditationInfoEnd') }}
                    </p>
                </div>
                <div class="form-grid">
                    <InputText :formInput="formData.accreditingBody" />
                    <InputText :formInput="formData.accreditingYear" class="year-input" />
                </div>
                <ul class="question-list">
                    <ApplicationQuestionRow :formInput="formData.isAccreditedByAuthority" />
                </ul>
                <div v-if="isVerificationRequired" class="sub-panel verification-panel">
                    <h3 class="card-subtitle">{{ $t('application.institutionalVerificationTitle') }}</h3>
                    <p class="card-intro">{{ $t('application.institutionalVerificationInfo') }}</p>
                    <div class="form-grid">
                        <InputText :formInput="formData.contactName" />
                        <InputText :formInput="formData.contactEmail" />
                    </div>
                    <div class="form-grid three-column">
                        <InputText :formInput="formData.contactCity" />
                        <InputSelect :formInput="formData.contactState" />
                        <InputText :formInput="formData.contactZip" />
                    </div>
                    <div class="form-grid">
                        <InputPhone :formInput="formData.contactPhone" />
                    </div>
                    <InputCheckbox
                        v-for="formInput in contactAttestationInputs"
                        :key="formInput.id"
                        :formInput="formInput"
                        class="attestation-checkbox"
                    />
                </div>
                <ul class="question-list">
                    <ApplicationQuestionRow :formInput="formData.isProgramEquivalent" />
                    <ApplicationQuestionRow :formInput="formData.hasResidence" />
                </ul>
            </section>
        </div>
    </ApplicationSectionLayout>
</template>

<script lang="ts" src="./Education.ts"></script>
<style scoped lang="less" src="./Education.less"></style>
