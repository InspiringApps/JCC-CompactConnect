<!--
    PersonalInformation.vue
    CompactConnect

    Created by InspiringApps on 11/24/2026.
-->

<template>
    <ApplicationSectionLayout
        class="personal-information-container"
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
        <section :key="formRenderKey" class="section-card" aria-labelledby="demographics-heading">
            <div class="card-group">
                <h2 id="demographics-heading" class="card-title">{{ $t('application.demographicsTitle') }}</h2>
                <div class="form-grid">
                    <InputText :formInput="formData.firstName" />
                    <InputText :formInput="formData.lastName" />
                    <InputText :formInput="formData.middleName" />
                    <InputSelect :formInput="formData.suffix" />
                    <InputDate
                        :formInput="formData.dob"
                        :yearRange="[1920, new Date().getFullYear()]"
                        :maxDate="new Date()"
                        :preventMinMaxNavigation="true"
                        :textInput="{ format: 'MM/dd/yyyy', openMenu: false }"
                        :startDate="new Date(1975, 0, 1)"
                    />
                    <InputSelect :formInput="formData.gender" />
                    <InputText :formInput="formData.professionalName" />
                    <InputText :formInput="formData.ssnLastFour" class="ssn-input" />
                    <InputSelect :formInput="formData.citizenship" />
                    <InputText :formInput="formData.placeOfBirth" />
                    <InputText :formInput="formData.npi" />
                    <div class="languages-container grid-start">
                        <InputSelect
                            :formInput="formData.languageSelect"
                            class="language-select"
                            @input="addLanguage"
                        />
                        <ul v-if="selectedLanguageOptions.length" class="language-pills">
                            <li
                                v-for="language in selectedLanguageOptions"
                                :key="language.value"
                                class="language-pill"
                            >
                                {{ language.name }}
                                <button
                                    type="button"
                                    class="text-like remove-language"
                                    :aria-label="$t('application.removeLanguage', { language: language.name })"
                                    @click="removeLanguage(language.value)"
                                >
                                    <CloseXIcon />
                                </button>
                            </li>
                        </ul>
                    </div>
                </div>
            </div>
            <div class="card-group">
                <h2 class="card-title">{{ $t('application.contactTitle') }}</h2>
                <div class="form-grid wide">
                    <InputText :formInput="formData.mailingAddress1" />
                    <InputText :formInput="formData.mailingAddress2" />
                </div>
                <div class="form-grid three-column">
                    <InputText :formInput="formData.mailingCity" />
                    <InputSelect :formInput="formData.mailingState" />
                    <InputText :formInput="formData.mailingZip" />
                </div>
                <div class="form-grid">
                    <InputPhone :formInput="formData.phone" />
                    <InputPhone :formInput="formData.altPhone" />
                </div>
            </div>
        </section>
    </ApplicationSectionLayout>
</template>

<script lang="ts" src="./PersonalInformation.ts"></script>
<style scoped lang="less" src="./PersonalInformation.less"></style>
