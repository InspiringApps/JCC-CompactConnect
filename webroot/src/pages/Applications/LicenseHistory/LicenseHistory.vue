<!--
    LicenseHistory.vue
    CompactConnect

    Created by InspiringApps on 11/24/2026.
-->

<template>
    <ApplicationSectionLayout
        class="license-history-container"
        :title="sectionTitle"
        :intro="$t('application.licenseHistoryIntro')"
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
        <div :key="formRenderKey" class="license-history-content">
            <section class="section-card licenses-card" aria-labelledby="licenses-heading">
                <h2 id="licenses-heading" class="visually-hidden">{{ sectionTitle }}</h2>
                <table v-if="licenses.length" class="licenses-table">
                    <thead>
                        <tr>
                            <th scope="col">{{ $t('application.jurisdictionHeader') }}</th>
                            <th scope="col">{{ $t('application.licenseNumberHeader') }}</th>
                            <th scope="col">{{ $t('application.issuedHeader') }}</th>
                            <th scope="col">{{ $t('common.status') }}</th>
                            <th scope="col"><span class="visually-hidden">{{ $t('common.edit') }}</span></th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr
                            v-for="(license, index) in licenses"
                            :key="`${license.state}-${license.licenseNumber}-${index}`"
                            class="license-row"
                        >
                            <td class="license-jurisdiction">{{ licenseStateName(license) }}</td>
                            <td class="license-number">{{ license.licenseNumber }}</td>
                            <td class="license-issued">{{ licenseIssueDate(license) }}</td>
                            <td class="license-status">
                                {{ $t(`application.licenseStatusOptions.${license.status}`) }}
                            </td>
                            <td class="license-actions">
                                <div v-if="isEditable" class="license-menu-container">
                                    <button
                                        type="button"
                                        class="text-like license-menu-toggle"
                                        :aria-label="$t('application.licenseActions', {
                                            jurisdiction: licenseStateName(license)
                                        })"
                                        :aria-expanded="openMenuIndex === index"
                                        @click="toggleLicenseMenu(index)"
                                    >
                                        <span class="menu-dot"></span>
                                        <span class="menu-dot"></span>
                                        <span class="menu-dot"></span>
                                    </button>
                                    <ul v-if="openMenuIndex === index" class="license-menu">
                                        <li>
                                            <button
                                                type="button"
                                                class="text-like license-menu-item edit-license"
                                                @click="openLicenseModal(index)"
                                            >
                                                {{ $t('common.edit') }}
                                            </button>
                                        </li>
                                        <li>
                                            <button
                                                type="button"
                                                class="text-like license-menu-item remove-license"
                                                @click="removeLicense(index)"
                                            >
                                                {{ $t('common.remove') }}
                                            </button>
                                        </li>
                                    </ul>
                                </div>
                            </td>
                        </tr>
                    </tbody>
                </table>
                <p v-else class="no-licenses">{{ $t('application.noLicenses') }}</p>
                <div
                    v-if="formData.licenses.errorMessage"
                    class="form-error licenses-error"
                    role="alert"
                >
                    {{ formData.licenses.errorMessage }}
                </div>
                <InputButton
                    v-if="isEditable"
                    :label="`+ ${$t('application.addLicense')}`"
                    :isTransparent="true"
                    :shouldHideMargin="true"
                    class="add-license-button"
                    @click="openLicenseModal()"
                />
            </section>
            <section
                v-if="isApit || isTap"
                class="section-card certifications-card"
                aria-labelledby="certifications-heading"
            >
                <h2 id="certifications-heading" class="card-title">{{ $t('application.certificationTitle') }}</h2>
                <p class="card-intro">{{ $t('application.certificationIntro') }}</p>
                <div v-if="isApit" class="card-group e-passport-group">
                    <h3 class="card-subtitle">{{ $t('application.ePassportTitle') }}</h3>
                    <div class="form-grid">
                        <div>
                            <InputText :formInput="formData.ePassportNumber" />
                            <p class="input-hint">{{ $t('application.mobilityNumberHint') }}</p>
                        </div>
                        <InputDate
                            :formInput="formData.ePassportIssueDate"
                            :yearRange="[1990, new Date().getFullYear()]"
                            :maxDate="new Date()"
                            :preventMinMaxNavigation="true"
                            :textInput="{ format: 'MM/dd/yyyy', openMenu: false }"
                        />
                    </div>
                </div>
                <div v-if="isTap" class="card-group ipc-group">
                    <h3 class="card-subtitle">{{ $t('application.ipcTitle') }}</h3>
                    <div class="form-grid">
                        <div>
                            <InputText :formInput="formData.ipcNumber" />
                            <p class="input-hint">{{ $t('application.mobilityNumberHint') }}</p>
                        </div>
                        <InputDate
                            :formInput="formData.ipcIssueDate"
                            :yearRange="[1990, new Date().getFullYear()]"
                            :maxDate="new Date()"
                            :preventMinMaxNavigation="true"
                            :textInput="{ format: 'MM/dd/yyyy', openMenu: false }"
                        />
                    </div>
                </div>
            </section>
        </div>
        <template #after-form>
            <Modal
                v-if="isLicenseModalOpen"
                modalId="license-modal"
                class="license-modal"
                :title="licenseModalTitle"
                :showActions="false"
                :closeOnBackgroundClick="true"
                @close-modal="closeLicenseModal"
                @keyup.esc="closeLicenseModal"
            >
                <template v-slot:content>
                    <form class="license-form" novalidate @submit.prevent="saveLicense">
                        <MockPopulate
                            :isEnabled="isMockPopulateEnabled"
                            class="license-mock-populate"
                            @selected="mockPopulateLicense"
                        />
                        <InputSelect :formInput="licenseFormData.state" />
                        <div class="license-form-row">
                            <InputDate
                                :formInput="licenseFormData.issueDate"
                                :yearRange="[1950, new Date().getFullYear()]"
                                :maxDate="new Date()"
                                :preventMinMaxNavigation="true"
                                :textInput="{ format: 'MM/dd/yyyy', openMenu: false }"
                            />
                            <InputText :formInput="licenseFormData.licenseNumber" />
                        </div>
                        <InputSelect :formInput="licenseFormData.status" />
                        <div class="license-form-actions">
                            <InputButton
                                :label="$t('common.cancel')"
                                :isTransparent="true"
                                :shouldHideMargin="true"
                                class="license-action-button cancel-license-button"
                                @click="closeLicenseModal"
                            />
                            <InputSubmit
                                :formInput="licenseFormData.submit"
                                :label="licenseSubmitLabel"
                                class="license-action-button save-license-button"
                            />
                        </div>
                    </form>
                </template>
            </Modal>
        </template>
    </ApplicationSectionLayout>
</template>

<script lang="ts" src="./LicenseHistory.ts"></script>
<style scoped lang="less" src="./LicenseHistory.less"></style>
